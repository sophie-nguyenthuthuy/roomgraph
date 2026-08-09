"""Content-stream interpreter: PDF operators in, flat geometry out.

Produces `Primitive` records in page space (y up, origin bottom-left, units of
1/72 inch). Beziers are flattened here because every downstream stage wants
polylines; the original curve is not needed once arcs have been fitted.

Optional-content markers (`/OC /MC0 BDC`) carry the CAD layer name. Keeping
them is what lets the wall extractor prefer `A-WALL` over furniture.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

from ..geom import Pt, dist
from .document import Document, Page
from .lexer import Keyword, Lexer, Name, Stream

Matrix = tuple[float, float, float, float, float, float]
IDENTITY: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def mat_mul(m: Matrix, n: Matrix) -> Matrix:
    a, b, c, d, e, f = m
    a2, b2, c2, d2, e2, f2 = n
    return (
        a * a2 + b * c2,
        a * b2 + b * d2,
        c * a2 + d * c2,
        c * b2 + d * d2,
        e * a2 + f * c2 + e2,
        e * b2 + f * d2 + f2,
    )


def mat_apply(m: Matrix, x: float, y: float) -> Pt:
    a, b, c, d, e, f = m
    return Pt(a * x + c * y + e, b * x + d * y + f)


def mat_scale(m: Matrix) -> float:
    """Average absolute scale factor, for converting line widths."""
    a, b, c, d = m[0], m[1], m[2], m[3]
    return (math.hypot(a, b) + math.hypot(c, d)) / 2.0


@dataclass
class Primitive:
    """One flattened subpath."""

    points: list[Pt]
    closed: bool = False
    stroked: bool = True
    filled: bool = False
    width: float = 0.0
    layer: str | None = None
    color: tuple[float, float, float] = (0.0, 0.0, 0.0)

    def length(self) -> float:
        n = len(self.points)
        total = sum(dist(self.points[i], self.points[i + 1]) for i in range(n - 1))
        if self.closed and n > 2:
            total += dist(self.points[-1], self.points[0])
        return total


@dataclass
class TextRun:
    text: str
    origin: Pt
    height: float
    angle: float
    layer: str | None = None


@dataclass
class PageGeometry:
    primitives: list[Primitive] = field(default_factory=list)
    texts: list[TextRun] = field(default_factory=list)
    media_box: tuple[float, float, float, float] = (0.0, 0.0, 612.0, 792.0)

    def layers(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for p in self.primitives:
            counts[p.layer or ""] = counts.get(p.layer or "", 0) + 1
        return counts


@dataclass
class _GState:
    ctm: Matrix = IDENTITY
    width: float = 1.0
    stroke_color: tuple[float, float, float] = (0.0, 0.0, 0.0)
    fill_color: tuple[float, float, float] = (0.0, 0.0, 0.0)
    font_key: str | None = None
    font_size: float = 0.0
    char_spacing: float = 0.0
    word_spacing: float = 0.0
    horiz_scale: float = 1.0
    leading: float = 0.0
    rise: float = 0.0


_BFCHAR = re.compile(rb"beginbfchar(.*?)endbfchar", re.S)
_BFRANGE = re.compile(rb"beginbfrange(.*?)endbfrange", re.S)
_HEXTOK = re.compile(rb"<([0-9A-Fa-f]+)>")


def _utf16_be(raw: bytes) -> str:
    try:
        return raw.decode("utf-16-be").replace("\x00", "")
    except UnicodeDecodeError:
        return raw.decode("latin-1", "replace")


class _Font:
    """Just enough font machinery to turn string bytes into readable text."""

    def __init__(self, doc: Document, fd: dict[str, Any]) -> None:
        self.two_byte = False
        self.cmap: dict[int, str] = {}
        subtype = doc.dget(fd, "Subtype")
        if isinstance(subtype, Name) and subtype.value == "Type0":
            self.two_byte = True
            enc = doc.dget(fd, "Encoding")
            if isinstance(enc, Name) and "Identity" not in enc.value:
                self.two_byte = True
        tu = doc.dget(fd, "ToUnicode")
        if isinstance(tu, Stream):
            try:
                self._parse_tounicode(doc.decode_stream(tu))
            except Exception:
                pass

    def _parse_tounicode(self, data: bytes) -> None:
        for m in _BFCHAR.finditer(data):
            toks = _HEXTOK.findall(m.group(1))
            for i in range(0, len(toks) - 1, 2):
                src = int(toks[i], 16)
                self.cmap[src] = _utf16_be(bytes.fromhex(toks[i + 1].decode()))
                if len(toks[i]) > 2:
                    self.two_byte = True
        for m in _BFRANGE.finditer(data):
            body = m.group(1)
            toks = _HEXTOK.findall(body)
            # Only the simple "<lo> <hi> <dst>" form; array form is rare in CAD exports.
            for i in range(0, len(toks) - 2, 3):
                lo, hi = int(toks[i], 16), int(toks[i + 1], 16)
                dst = bytes.fromhex(toks[i + 2].decode())
                if len(toks[i]) > 2:
                    self.two_byte = True
                if hi - lo > 65535:
                    continue
                base = int.from_bytes(dst, "big")
                width = max(1, len(dst) // 2)
                for k in range(hi - lo + 1):
                    self.cmap[lo + k] = _utf16_be((base + k).to_bytes(width * 2, "big"))

    def decode(self, raw: bytes) -> str:
        out: list[str] = []
        if self.two_byte:
            for i in range(0, len(raw) - 1, 2):
                code = (raw[i] << 8) | raw[i + 1]
                out.append(self.cmap.get(code, ""))
        else:
            for byte in raw:
                out.append(self.cmap.get(byte) or bytes([byte]).decode("cp1252", "replace"))
        return "".join(out)


class ContentInterpreter:
    MAX_FORM_DEPTH = 12

    def __init__(self, doc: Document, curve_steps: int = 16) -> None:
        self.doc = doc
        self.curve_steps = curve_steps
        self._font_cache: dict[int, _Font] = {}

    def run_page(self, page: Page) -> PageGeometry:
        geo = PageGeometry(media_box=page.media_box)
        base = self._page_matrix(page)
        self._execute(page.content, page.resources, _GState(ctm=base), geo, depth=0)
        return geo

    def _page_matrix(self, page: Page) -> Matrix:
        """Normalise /Rotate away so downstream code always sees an upright plan."""
        x0, y0, x1, y1 = page.media_box
        w, h = x1 - x0, y1 - y0
        rot = page.rotate % 360
        shift: Matrix = (1.0, 0.0, 0.0, 1.0, -x0, -y0)
        if rot == 90:
            return mat_mul(shift, (0.0, 1.0, -1.0, 0.0, h, 0.0))
        if rot == 180:
            return mat_mul(shift, (-1.0, 0.0, 0.0, -1.0, w, h))
        if rot == 270:
            return mat_mul(shift, (0.0, -1.0, 1.0, 0.0, 0.0, w))
        return shift

    # -- main loop ---------------------------------------------------------
    def _execute(
        self,
        content: bytes,
        resources: dict[str, Any],
        gs: _GState,
        geo: PageGeometry,
        depth: int,
    ) -> None:
        lex = Lexer(content)
        stack: list[Any] = []
        gstack: list[_GState] = []
        layer_stack: list[str | None] = []
        current_layer: str | None = None

        path: list[list[Pt]] = []
        sub: list[Pt] = []
        closed_flags: list[bool] = []
        start: Pt | None = None
        cur: Pt | None = None

        tm: Matrix = IDENTITY
        tlm: Matrix = IDENTITY
        in_text = False

        def num(i: int, default: float = 0.0) -> float:
            try:
                v = stack[i]
                return float(v) if isinstance(v, int | float) else default
            except (IndexError, TypeError, ValueError):
                return default

        def flush_sub() -> None:
            nonlocal sub
            if len(sub) >= 2:
                path.append(sub)
                closed_flags.append(False)
            sub = []

        def emit(stroked: bool, filled: bool, close_all: bool) -> None:
            nonlocal path, sub, closed_flags, start, cur
            flush_sub()
            for pts, was_closed in zip(path, closed_flags, strict=False):
                if len(pts) < 2:
                    continue
                geo.primitives.append(
                    Primitive(
                        points=pts,
                        closed=was_closed or close_all or filled,
                        stroked=stroked,
                        filled=filled,
                        width=gs.width * mat_scale(gs.ctm),
                        layer=current_layer,
                        color=gs.stroke_color if stroked else gs.fill_color,
                    )
                )
            path, closed_flags, sub, start, cur = [], [], [], None, None

        while True:
            tok = lex.next_token()
            if tok is None:
                break
            if not isinstance(tok, Keyword):
                stack.append(tok)
                if len(stack) > 64:
                    del stack[:-32]
                continue
            op = tok.value

            if op == "<<":
                stack.append(lex._parse_dict())
                continue
            if op == "[":
                stack.append(lex._parse_array())
                continue
            if op in ("]", ">>", "null"):
                continue

            # -- graphics state
            if op == "q":
                gstack.append(_GState(**vars(gs)))
            elif op == "Q":
                if gstack:
                    gs = gstack.pop()
            elif op == "cm" and len(stack) >= 6:
                m = (num(-6), num(-5), num(-4), num(-3), num(-2), num(-1))
                gs.ctm = mat_mul(m, gs.ctm)
            elif op == "w" and stack:
                gs.width = num(-1, 1.0)
            elif op == "gs":
                pass  # ExtGState affects appearance only

            # -- colour (enough to spot construction vs annotation ink)
            elif op in ("g", "G") and stack:
                v = num(-1)
                c = (v, v, v)
                if op == "g":
                    gs.fill_color = c
                else:
                    gs.stroke_color = c
            elif op in ("rg", "RG") and len(stack) >= 3:
                c = (num(-3), num(-2), num(-1))
                if op == "rg":
                    gs.fill_color = c
                else:
                    gs.stroke_color = c
            elif op in ("k", "K") and len(stack) >= 4:
                cy, ma, ye, bl = num(-4), num(-3), num(-2), num(-1)
                c = ((1 - cy) * (1 - bl), (1 - ma) * (1 - bl), (1 - ye) * (1 - bl))
                if op == "k":
                    gs.fill_color = c
                else:
                    gs.stroke_color = c
            elif op in ("sc", "scn", "SC", "SCN"):
                nums = [v for v in stack if isinstance(v, int | float)]
                c = None
                if len(nums) >= 3:
                    c = (float(nums[-3]), float(nums[-2]), float(nums[-1]))
                elif len(nums) == 1:
                    c = (float(nums[-1]),) * 3
                if c is not None:
                    if op in ("sc", "scn"):
                        gs.fill_color = c
                    else:
                        gs.stroke_color = c

            # -- path construction
            elif op == "m" and len(stack) >= 2:
                flush_sub()
                cur = mat_apply(gs.ctm, num(-2), num(-1))
                start = cur
                sub = [cur]
            elif op == "l" and len(stack) >= 2:
                cur = mat_apply(gs.ctm, num(-2), num(-1))
                if not sub:
                    sub = [cur]
                else:
                    sub.append(cur)
            elif op in ("c", "v", "y") and cur is not None:
                if op == "c" and len(stack) >= 6:
                    c1 = mat_apply(gs.ctm, num(-6), num(-5))
                    c2 = mat_apply(gs.ctm, num(-4), num(-3))
                    p3 = mat_apply(gs.ctm, num(-2), num(-1))
                elif op == "v" and len(stack) >= 4:
                    c1 = cur
                    c2 = mat_apply(gs.ctm, num(-4), num(-3))
                    p3 = mat_apply(gs.ctm, num(-2), num(-1))
                elif op == "y" and len(stack) >= 4:
                    c1 = mat_apply(gs.ctm, num(-4), num(-3))
                    p3 = mat_apply(gs.ctm, num(-2), num(-1))
                    c2 = p3
                else:
                    stack.clear()
                    continue
                sub.extend(self._flatten_bezier(cur, c1, c2, p3))
                cur = p3
            elif op == "h":
                if len(sub) >= 2:
                    path.append(sub)
                    closed_flags.append(True)
                sub = []
                cur = start
            elif op == "re" and len(stack) >= 4:
                flush_sub()
                x, y, w, h = num(-4), num(-3), num(-2), num(-1)
                corners = [
                    mat_apply(gs.ctm, x, y),
                    mat_apply(gs.ctm, x + w, y),
                    mat_apply(gs.ctm, x + w, y + h),
                    mat_apply(gs.ctm, x, y + h),
                ]
                path.append(corners)
                closed_flags.append(True)
                cur = start = corners[0]

            # -- path painting
            elif op in ("S", "s"):
                emit(stroked=True, filled=False, close_all=(op == "s"))
            elif op in ("f", "F", "f*"):
                emit(stroked=False, filled=True, close_all=True)
            elif op in ("B", "B*", "b", "b*"):
                emit(stroked=True, filled=True, close_all=True)
            elif op == "n":
                path, closed_flags, sub, cur, start = [], [], [], None, None
            elif op in ("W", "W*"):
                pass  # clip: the following `n` discards the path

            # -- text
            elif op == "BT":
                in_text = True
                tm = tlm = IDENTITY
            elif op == "ET":
                in_text = False
            elif op == "Tf" and len(stack) >= 2:
                gs.font_key = stack[-2].value if isinstance(stack[-2], Name) else None
                gs.font_size = num(-1)
            elif op == "TL" and stack:
                gs.leading = num(-1)
            elif op == "Tc" and stack:
                gs.char_spacing = num(-1)
            elif op == "Tw" and stack:
                gs.word_spacing = num(-1)
            elif op == "Tz" and stack:
                gs.horiz_scale = num(-1, 100.0) / 100.0
            elif op == "Ts" and stack:
                gs.rise = num(-1)
            elif op == "Tm" and len(stack) >= 6:
                tm = tlm = (num(-6), num(-5), num(-4), num(-3), num(-2), num(-1))
            elif op in ("Td", "TD") and len(stack) >= 2:
                if op == "TD":
                    gs.leading = -num(-1)
                tlm = mat_mul((1.0, 0.0, 0.0, 1.0, num(-2), num(-1)), tlm)
                tm = tlm
            elif op == "T*":
                tlm = mat_mul((1.0, 0.0, 0.0, 1.0, 0.0, -gs.leading), tlm)
                tm = tlm
            elif op in ("Tj", "TJ", "'", '"'):
                if op in ("'", '"'):
                    tlm = mat_mul((1.0, 0.0, 0.0, 1.0, 0.0, -gs.leading), tlm)
                    tm = tlm
                arg = stack[-1] if stack else b""
                chunks = arg if isinstance(arg, list) else [arg]
                raw = b"".join(c for c in chunks if isinstance(c, bytes))
                text = self._decode_text(raw, resources, gs.font_key)
                if text.strip() and in_text:
                    trm = mat_mul(
                        (gs.font_size * gs.horiz_scale, 0.0, 0.0, gs.font_size, 0.0, gs.rise),
                        mat_mul(tm, gs.ctm),
                    )
                    origin = Pt(trm[4], trm[5])
                    height = math.hypot(trm[2], trm[3])
                    angle = math.atan2(trm[1], trm[0])
                    geo.texts.append(
                        TextRun(text.strip(), origin, height, angle, current_layer)
                    )
                    advance = 0.6 * gs.font_size * gs.horiz_scale * max(1, len(text))
                    tm = mat_mul((1.0, 0.0, 0.0, 1.0, advance, 0.0), tm)

            # -- optional content (CAD layers)
            elif op in ("BDC", "BMC"):
                layer_stack.append(current_layer)
                name = self._layer_name(stack, resources)
                if name:
                    current_layer = name
            elif op == "EMC":
                current_layer = layer_stack.pop() if layer_stack else None

            # -- forms
            elif op == "Do" and stack and depth < self.MAX_FORM_DEPTH:
                self._do_xobject(stack[-1], resources, gs, geo, depth)

            stack.clear()

        # Unbalanced q/Q or a missing painting op at EOF: keep what we have.
        if sub or path:
            emit(stroked=True, filled=False, close_all=False)

    # -- helpers -----------------------------------------------------------
    def _flatten_bezier(self, p0: Pt, p1: Pt, p2: Pt, p3: Pt) -> list[Pt]:
        ctrl_len = dist(p0, p1) + dist(p1, p2) + dist(p2, p3)
        steps = max(4, min(self.curve_steps, int(ctrl_len / 2.0) + 4))
        out: list[Pt] = []
        for i in range(1, steps + 1):
            t = i / steps
            u = 1 - t
            x = u**3 * p0.x + 3 * u * u * t * p1.x + 3 * u * t * t * p2.x + t**3 * p3.x
            y = u**3 * p0.y + 3 * u * u * t * p1.y + 3 * u * t * t * p2.y + t**3 * p3.y
            out.append(Pt(x, y))
        return out

    def _layer_name(self, stack: list[Any], resources: dict[str, Any]) -> str | None:
        if len(stack) < 2:
            return None
        tag, prop = stack[-2], stack[-1]
        if not isinstance(tag, Name) or tag.value != "OC":
            return None
        target = prop
        if isinstance(prop, Name):
            props = self.doc.dget(resources, "Properties", {})
            target = self.doc.dget(props, prop.value) if isinstance(props, dict) else None
        target = self.doc.resolve(target)
        if isinstance(target, dict):
            nm = self.doc.dget(target, "Name")
            if isinstance(nm, bytes):
                return _utf16_be(nm[2:]) if nm[:2] == b"\xfe\xff" else nm.decode("cp1252", "replace")
            if isinstance(nm, str):
                return nm
            ocgs = self.doc.dget(target, "OCGs")
            first = self.doc.resolve(ocgs[0]) if isinstance(ocgs, list) and ocgs else self.doc.resolve(ocgs)
            if isinstance(first, dict):
                nm = self.doc.dget(first, "Name")
                if isinstance(nm, bytes):
                    return nm.decode("cp1252", "replace")
        return None

    def _decode_text(self, raw: bytes, resources: dict[str, Any], key: str | None) -> str:
        if not raw:
            return ""
        fonts = self.doc.dget(resources, "Font", {})
        fd = self.doc.dget(fonts, key) if (isinstance(fonts, dict) and key) else None
        if not isinstance(fd, dict):
            return raw.decode("cp1252", "replace")
        cache_key = id(fd)
        font = self._font_cache.get(cache_key)
        if font is None:
            font = _Font(self.doc, fd)
            self._font_cache[cache_key] = font
        return font.decode(raw)

    def _do_xobject(
        self,
        name: Any,
        resources: dict[str, Any],
        gs: _GState,
        geo: PageGeometry,
        depth: int,
    ) -> None:
        if not isinstance(name, Name):
            return
        xobjs = self.doc.dget(resources, "XObject", {})
        xo = self.doc.dget(xobjs, name.value) if isinstance(xobjs, dict) else None
        if not isinstance(xo, Stream):
            return
        if self.doc.dget(xo.dict, "Subtype") != Name("Form"):
            return  # images are out of scope for vector extraction
        sub_gs = _GState(**vars(gs))
        m = self.doc.dget(xo.dict, "Matrix")
        if isinstance(m, list) and len(m) == 6:
            vals = [float(self.doc.resolve(v) or 0) for v in m]
            sub_gs.ctm = mat_mul(tuple(vals), gs.ctm)  # type: ignore[arg-type]
        sub_res = self.doc.dget(xo.dict, "Resources", resources)
        try:
            body = self.doc.decode_stream(xo)
        except Exception:
            return
        self._execute(body, sub_res if isinstance(sub_res, dict) else resources, sub_gs, geo, depth + 1)


def read_pdf(path: str, page_index: int = 0, curve_steps: int = 16) -> PageGeometry:
    doc = Document.from_path(path)
    pages = doc.pages()
    if not pages:
        raise ValueError(f"{path}: no pages found")
    if page_index >= len(pages):
        raise ValueError(f"{path}: page {page_index} out of range (has {len(pages)})")
    return ContentInterpreter(doc, curve_steps=curve_steps).run_page(pages[page_index])
