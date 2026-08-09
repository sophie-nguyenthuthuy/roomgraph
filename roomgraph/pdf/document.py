"""PDF document: object store, stream decoding, page tree.

Object lookup is deliberately forgiving. Rather than trusting the cross-reference
table (which CAD exporters and downstream optimisers routinely leave stale), we
scan the whole file for `N G obj` headers and index those. Cross-reference
streams are then only needed for objects living inside object streams.
"""

from __future__ import annotations

import re
import zlib
from dataclasses import dataclass
from typing import Any

from .lexer import Lexer, Name, Ref, Stream

OBJ_HEADER = re.compile(rb"(?<![0-9])(\d{1,10})\s+(\d{1,5})\s+obj\b")


class PdfError(Exception):
    pass


def _apply_predictor(data: bytes, params: dict[str, Any]) -> bytes:
    """PNG predictors (10-15), as used by FlateDecode'd xref streams."""
    pred = int(params.get("Predictor", 1) or 1)
    if pred < 2:
        return data
    colors = int(params.get("Colors", 1) or 1)
    bpc = int(params.get("BitsPerComponent", 8) or 8)
    columns = int(params.get("Columns", 1) or 1)
    bpp = max(1, (colors * bpc + 7) // 8)
    row_len = (columns * colors * bpc + 7) // 8
    out = bytearray()
    prev = bytearray(row_len)
    i = 0
    while i + 1 + row_len <= len(data) + row_len and i < len(data):
        ft = data[i]
        row = bytearray(data[i + 1 : i + 1 + row_len])
        if len(row) < row_len:
            row.extend(b"\x00" * (row_len - len(row)))
        i += 1 + row_len
        if ft == 1:
            for j in range(bpp, row_len):
                row[j] = (row[j] + row[j - bpp]) & 0xFF
        elif ft == 2:
            for j in range(row_len):
                row[j] = (row[j] + prev[j]) & 0xFF
        elif ft == 3:
            for j in range(row_len):
                left = row[j - bpp] if j >= bpp else 0
                row[j] = (row[j] + ((left + prev[j]) >> 1)) & 0xFF
        elif ft == 4:
            for j in range(row_len):
                a = row[j - bpp] if j >= bpp else 0
                b = prev[j]
                c = prev[j - bpp] if j >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                row[j] = (row[j] + pr) & 0xFF
        out.extend(row)
        prev = row
    return bytes(out)


def _ascii_hex_decode(data: bytes) -> bytes:
    digits = bytes(c for c in data.split(b">")[0] if c not in b" \t\r\n\x0c\x00")
    if len(digits) % 2:
        digits += b"0"
    try:
        return bytes.fromhex(digits.decode("latin-1"))
    except ValueError:
        return b""


def _ascii85_decode(data: bytes) -> bytes:
    import base64

    body = data.split(b"~>")[0].replace(b"<~", b"")
    body = bytes(c for c in body if c not in b" \t\r\n\x0c\x00")
    try:
        return base64.a85decode(body)
    except Exception:
        return b""


def _run_length_decode(data: bytes) -> bytes:
    out = bytearray()
    i = 0
    while i < len(data):
        n = data[i]
        i += 1
        if n == 128:
            break
        if n < 128:
            out.extend(data[i : i + n + 1])
            i += n + 1
        else:
            if i < len(data):
                out.extend(bytes([data[i]]) * (257 - n))
                i += 1
    return bytes(out)


@dataclass
class Page:
    index: int
    obj: dict[str, Any]
    media_box: tuple[float, float, float, float]
    resources: dict[str, Any]
    content: bytes
    rotate: int = 0


class Document:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self._offsets: dict[int, int] = {}
        self._cache: dict[int, Any] = {}
        self._compressed: dict[int, tuple[int, int]] = {}
        self._scan_objects()
        self._load_object_streams()
        self.trailer = self._find_trailer()

    @classmethod
    def from_path(cls, path: str) -> Document:
        with open(path, "rb") as fh:
            return cls(fh.read())

    # -- object index ------------------------------------------------------
    def _scan_objects(self) -> None:
        for m in OBJ_HEADER.finditer(self.data):
            # Later definitions win: incremental updates append to the file.
            self._offsets[int(m.group(1))] = m.end()

    def _load_object_streams(self) -> None:
        """Index objects packed inside /Type /ObjStm containers."""
        for num in list(self._offsets):
            try:
                obj = self.get(num)
            except Exception:
                continue
            if not isinstance(obj, Stream):
                continue
            if obj.dict.get("Type") != Name("ObjStm"):
                continue
            try:
                payload = self.decode_stream(obj)
                n = int(self.resolve(obj.dict.get("N", 0)) or 0)
                first = int(self.resolve(obj.dict.get("First", 0)) or 0)
            except Exception:
                continue
            head = Lexer(payload[:first])
            pairs: list[int] = []
            for _ in range(n * 2):
                tok = head.next_token()
                if not isinstance(tok, int):
                    break
                pairs.append(tok)
            for i in range(0, len(pairs) - 1, 2):
                onum, ooff = pairs[i], pairs[i + 1]
                if onum in self._offsets:
                    continue  # a top-level definition takes precedence
                self._compressed[onum] = (num, first + ooff)

    def _find_trailer(self) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        for m in re.finditer(rb"trailer", self.data):
            lex = Lexer(self.data, m.end())
            obj = lex.parse_object()
            if isinstance(obj, dict):
                merged.update(obj)
        if "Root" not in merged:
            # Cross-reference stream file: the xref stream dict *is* the trailer.
            for num in self._offsets:
                try:
                    o = self.get(num)
                except Exception:
                    continue
                if isinstance(o, Stream) and o.dict.get("Type") == Name("XRef"):
                    merged.update(o.dict)
            if "Root" not in merged:
                for num in self._offsets:
                    try:
                        o = self.get(num)
                    except Exception:
                        continue
                    if isinstance(o, dict) and o.get("Type") == Name("Catalog"):
                        merged["Root"] = Ref(num, 0)
                        break
        return merged

    # -- access ------------------------------------------------------------
    def get(self, num: int) -> Any:
        if num in self._cache:
            return self._cache[num]
        self._cache[num] = None  # guard against reference cycles
        value: Any = None
        if num in self._offsets:
            value = self._parse_at(self._offsets[num])
        elif num in self._compressed:
            container, off = self._compressed[num]
            payload = self.decode_stream(self.get(container))
            value = Lexer(payload, off).parse_object()
        self._cache[num] = value
        return value

    def _parse_at(self, pos: int) -> Any:
        lex = Lexer(self.data, pos)
        obj = lex.parse_object()
        lex.skip_ws()
        if self.data[lex.pos : lex.pos + 6] == b"stream" and isinstance(obj, dict):
            p = lex.pos + 6
            if self.data[p : p + 2] == b"\r\n":
                p += 2
            elif self.data[p : p + 1] in (b"\n", b"\r"):
                p += 1
            length = self.resolve(obj.get("Length"))
            raw = b""
            if isinstance(length, int) and length >= 0:
                raw = self.data[p : p + length]
                tail = self.data[p + length : p + length + 20]
                if b"endstream" not in tail:
                    raw = b""  # /Length lied; fall back to scanning
            if not raw:
                end = self.data.find(b"endstream", p)
                raw = self.data[p:end] if end != -1 else self.data[p:]
                raw = raw.rstrip(b"\r\n")
            return Stream(obj, raw)
        return obj

    def resolve(self, obj: Any, depth: int = 0) -> Any:
        while isinstance(obj, Ref) and depth < 64:
            obj = self.get(obj.num)
            depth += 1
        return obj

    def dget(self, d: dict[str, Any] | None, key: str, default: Any = None) -> Any:
        if not isinstance(d, dict):
            return default
        v = self.resolve(d.get(key, default))
        return default if v is None else v

    # -- streams -----------------------------------------------------------
    def decode_stream(self, stream: Stream) -> bytes:
        if not isinstance(stream, Stream):
            raise PdfError("not a stream")
        data = stream.raw
        filters = self.resolve(stream.dict.get("Filter"))
        if filters is None:
            return data
        if isinstance(filters, Name):
            filters = [filters]
        params = self.resolve(stream.dict.get("DecodeParms"))
        if not isinstance(params, list):
            params = [params]
        for i, f in enumerate(filters):
            f = self.resolve(f)
            if not isinstance(f, Name):
                continue
            parm = self.resolve(params[i]) if i < len(params) else None
            parm = parm if isinstance(parm, dict) else {}
            parm = {k: self.resolve(v) for k, v in parm.items()}
            if f.value in ("FlateDecode", "Fl"):
                data = self._inflate(data)
                data = _apply_predictor(data, parm)
            elif f.value in ("ASCIIHexDecode", "AHx"):
                data = _ascii_hex_decode(data)
            elif f.value in ("ASCII85Decode", "A85"):
                data = _ascii85_decode(data)
            elif f.value in ("RunLengthDecode", "RL"):
                data = _run_length_decode(data)
            elif f.value in ("DCTDecode", "JPXDecode", "CCITTFaxDecode", "JBIG2Decode"):
                # Raster image payloads: out of scope, hand back untouched.
                return data
            else:
                raise PdfError(f"unsupported filter {f.value}")
        return data

    @staticmethod
    def _inflate(data: bytes) -> bytes:
        for wbits in (15, -15, 47):
            try:
                return zlib.decompress(data, wbits)
            except zlib.error:
                continue
        # Truncated streams are common in the wild; salvage what we can.
        d = zlib.decompressobj()
        try:
            return d.decompress(data)
        except zlib.error:
            return b""

    # -- pages -------------------------------------------------------------
    def pages(self) -> list[Page]:
        root = self.resolve(self.trailer.get("Root"))
        pages_root = self.dget(root, "Pages") if isinstance(root, dict) else None
        collected: list[dict[str, Any]] = []
        if isinstance(pages_root, dict):
            self._walk_pages(pages_root, {}, collected, set())
        if not collected:
            # No usable page tree: fall back to every /Type /Page object.
            for num in sorted(self._offsets) + sorted(self._compressed):
                o = self.get(num)
                if isinstance(o, dict) and o.get("Type") == Name("Page"):
                    collected.append(o)
        out: list[Page] = []
        for i, node in enumerate(collected):
            mb = self.dget(node, "MediaBox", [0, 0, 612, 792])
            mb = [float(self.resolve(v) or 0) for v in mb] if isinstance(mb, list) else [0, 0, 612, 792]
            if len(mb) != 4:
                mb = [0.0, 0.0, 612.0, 792.0]
            box = (min(mb[0], mb[2]), min(mb[1], mb[3]), max(mb[0], mb[2]), max(mb[1], mb[3]))
            res = self.dget(node, "Resources", {}) or {}
            out.append(
                Page(
                    index=i,
                    obj=node,
                    media_box=box,
                    resources=res if isinstance(res, dict) else {},
                    content=self._page_content(node),
                    rotate=int(self.dget(node, "Rotate", 0) or 0),
                )
            )
        return out

    def _walk_pages(
        self,
        node: dict[str, Any],
        inherited: dict[str, Any],
        out: list[dict[str, Any]],
        seen: set[int],
    ) -> None:
        merged = dict(inherited)
        for key in ("Resources", "MediaBox", "CropBox", "Rotate"):
            if key in node:
                merged[key] = node[key]
        kids = self.dget(node, "Kids")
        if node.get("Type") == Name("Page") or (kids is None and "Contents" in node):
            page = dict(merged)
            page.update(node)
            out.append(page)
            return
        if not isinstance(kids, list):
            return
        for kid in kids:
            key = kid.num if isinstance(kid, Ref) else id(kid)
            if key in seen:
                continue
            seen.add(key)
            child = self.resolve(kid)
            if isinstance(child, dict):
                self._walk_pages(child, merged, out, seen)

    def _page_content(self, node: dict[str, Any]) -> bytes:
        contents = self.resolve(node.get("Contents"))
        chunks: list[bytes] = []
        items = contents if isinstance(contents, list) else [contents]
        for item in items:
            item = self.resolve(item)
            if isinstance(item, Stream):
                try:
                    chunks.append(self.decode_stream(item))
                except PdfError:
                    continue
        return b"\n".join(chunks)
