"""A small RGB canvas and a GIF89a encoder, both stdlib-only.

Written from scratch so the animated GIF -- the thing that actually gets the
project looked at -- needs no image library. Floor plans are overwhelmingly
rectilinear, so filled spans land on exact pixel boundaries and we get away
without supersampling; only the diagonal graph edges are anti-aliased, and
those are cheap because there are few of them.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence

RGB = tuple[int, int, int]


def mix(a: RGB, b: RGB, t: float) -> RGB:
    """Blend a toward b. Fades are done at the colour level, not per pixel."""
    t = max(0.0, min(1.0, t))
    return (
        int(round(a[0] + (b[0] - a[0]) * t)),
        int(round(a[1] + (b[1] - a[1]) * t)),
        int(round(a[2] + (b[2] - a[2]) * t)),
    )


class Canvas:
    def __init__(self, width: int, height: int, background: RGB = (255, 255, 255)) -> None:
        self.w = width
        self.h = height
        self.buf = bytearray(bytes(background) * (width * height))

    def clear(self, colour: RGB) -> None:
        self.buf[:] = bytes(colour) * (self.w * self.h)

    def _span(self, y: int, x0: int, x1: int, colour: RGB) -> None:
        if y < 0 or y >= self.h:
            return
        x0 = max(0, int(math.floor(x0)))
        x1 = min(self.w, int(math.ceil(x1)))
        if x1 <= x0:
            return
        base = (y * self.w + x0) * 3
        self.buf[base : base + (x1 - x0) * 3] = bytes(colour) * (x1 - x0)

    def pixel(self, x: int, y: int, colour: RGB, alpha: float = 1.0) -> None:
        if not (0 <= x < self.w and 0 <= y < self.h):
            return
        i = (y * self.w + x) * 3
        if alpha >= 1.0:
            self.buf[i : i + 3] = bytes(colour)
            return
        if alpha <= 0.0:
            return
        for k in range(3):
            self.buf[i + k] = int(round(self.buf[i + k] * (1 - alpha) + colour[k] * alpha))

    def fill_polygon(self, pts: Sequence[tuple[float, float]], colour: RGB) -> None:
        """Even-odd scanline fill."""
        if len(pts) < 3:
            return
        ys = [p[1] for p in pts]
        y0 = max(0, int(math.floor(min(ys))))
        y1 = min(self.h - 1, int(math.ceil(max(ys))))
        n = len(pts)
        for y in range(y0, y1 + 1):
            yc = y + 0.5
            xs: list[float] = []
            for i in range(n):
                ax, ay = pts[i]
                bx, by = pts[(i + 1) % n]
                if (ay > yc) != (by > yc):
                    xs.append(ax + (yc - ay) * (bx - ax) / (by - ay))
            xs.sort()
            for k in range(0, len(xs) - 1, 2):
                self._span(y, xs[k], xs[k + 1], colour)

    def fill_circle(self, cx: float, cy: float, r: float, colour: RGB) -> None:
        if r <= 0:
            return
        for y in range(max(0, int(cy - r)), min(self.h, int(cy + r) + 2)):
            dy = (y + 0.5) - cy
            if abs(dy) > r:
                continue
            dx = math.sqrt(max(0.0, r * r - dy * dy))
            self._span(y, cx - dx, cx + dx, colour)

    def ring(self, cx: float, cy: float, r: float, thickness: float, colour: RGB) -> None:
        inner = max(0.0, r - thickness)
        for y in range(max(0, int(cy - r)), min(self.h, int(cy + r) + 2)):
            dy = (y + 0.5) - cy
            if abs(dy) > r:
                continue
            outer_dx = math.sqrt(max(0.0, r * r - dy * dy))
            if abs(dy) < inner:
                inner_dx = math.sqrt(max(0.0, inner * inner - dy * dy))
                self._span(y, cx - outer_dx, cx - inner_dx, colour)
                self._span(y, cx + inner_dx, cx + outer_dx, colour)
            else:
                self._span(y, cx - outer_dx, cx + outer_dx, colour)

    def thick_line(
        self,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        width: float,
        colour: RGB,
        round_caps: bool = True,
    ) -> None:
        dx, dy = x1 - x0, y1 - y0
        ln = math.hypot(dx, dy)
        if ln < 1e-9:
            self.fill_circle(x0, y0, width / 2.0, colour)
            return
        ux, uy = dx / ln, dy / ln
        nx, ny = -uy * width / 2.0, ux * width / 2.0
        self.fill_polygon(
            [
                (x0 + nx, y0 + ny),
                (x1 + nx, y1 + ny),
                (x1 - nx, y1 - ny),
                (x0 - nx, y0 - ny),
            ],
            colour,
        )
        if round_caps and width > 2.5:
            self.fill_circle(x0, y0, width / 2.0, colour)
            self.fill_circle(x1, y1, width / 2.0, colour)

    def aa_line(self, x0: float, y0: float, x1: float, y1: float, colour: RGB, width: float = 1.6) -> None:
        """Anti-aliased line, for the diagonal graph edges."""
        dx, dy = x1 - x0, y1 - y0
        steps = int(max(abs(dx), abs(dy)) * 2) + 1
        half = width / 2.0
        for i in range(steps + 1):
            t = i / steps
            px, py = x0 + dx * t, y0 + dy * t
            ix, iy = int(math.floor(px)), int(math.floor(py))
            for ox in range(-int(half) - 1, int(half) + 2):
                for oy in range(-int(half) - 1, int(half) + 2):
                    d = math.hypot((ix + ox + 0.5) - px, (iy + oy + 0.5) - py)
                    a = max(0.0, min(1.0, half + 0.5 - d))
                    if a > 0:
                        self.pixel(ix + ox, iy + oy, colour, a)

    # -- text: a 5x7 bitmap font, enough for room labels ---------------------
    def text(self, s: str, x: float, y: float, colour: RGB, scale: int = 2) -> None:
        cx = x
        for ch in s.upper():
            glyph = _FONT.get(ch)
            if glyph is None:
                cx += 4 * scale
                continue
            for row, bits in enumerate(glyph):
                for col in range(5):
                    if bits & (1 << (4 - col)):
                        self._rect(cx + col * scale, y + row * scale, scale, scale, colour)
            cx += 6 * scale

    def text_width(self, s: str, scale: int = 2) -> float:
        return len(s) * 6 * scale

    def _rect(self, x: float, y: float, w: int, h: int, colour: RGB) -> None:
        for yy in range(int(y), int(y) + h):
            self._span(yy, x, x + w, colour)

    # -- output --------------------------------------------------------------
    def to_rgb_rows(self) -> bytes:
        return bytes(self.buf)


_FONT: dict[str, list[int]] = {
    " ": [0, 0, 0, 0, 0, 0, 0],
    "A": [0x0E, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11],
    "B": [0x1E, 0x11, 0x11, 0x1E, 0x11, 0x11, 0x1E],
    "C": [0x0E, 0x11, 0x10, 0x10, 0x10, 0x11, 0x0E],
    "D": [0x1E, 0x11, 0x11, 0x11, 0x11, 0x11, 0x1E],
    "E": [0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x1F],
    "F": [0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x10],
    "G": [0x0E, 0x11, 0x10, 0x17, 0x11, 0x11, 0x0F],
    "H": [0x11, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11],
    "I": [0x0E, 0x04, 0x04, 0x04, 0x04, 0x04, 0x0E],
    "J": [0x07, 0x02, 0x02, 0x02, 0x02, 0x12, 0x0C],
    "K": [0x11, 0x12, 0x14, 0x18, 0x14, 0x12, 0x11],
    "L": [0x10, 0x10, 0x10, 0x10, 0x10, 0x10, 0x1F],
    "M": [0x11, 0x1B, 0x15, 0x15, 0x11, 0x11, 0x11],
    "N": [0x11, 0x19, 0x15, 0x13, 0x11, 0x11, 0x11],
    "O": [0x0E, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E],
    "P": [0x1E, 0x11, 0x11, 0x1E, 0x10, 0x10, 0x10],
    "Q": [0x0E, 0x11, 0x11, 0x11, 0x15, 0x12, 0x0D],
    "R": [0x1E, 0x11, 0x11, 0x1E, 0x14, 0x12, 0x11],
    "S": [0x0F, 0x10, 0x10, 0x0E, 0x01, 0x01, 0x1E],
    "T": [0x1F, 0x04, 0x04, 0x04, 0x04, 0x04, 0x04],
    "U": [0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E],
    "V": [0x11, 0x11, 0x11, 0x11, 0x11, 0x0A, 0x04],
    "W": [0x11, 0x11, 0x11, 0x15, 0x15, 0x1B, 0x11],
    "X": [0x11, 0x11, 0x0A, 0x04, 0x0A, 0x11, 0x11],
    "Y": [0x11, 0x11, 0x0A, 0x04, 0x04, 0x04, 0x04],
    "Z": [0x1F, 0x01, 0x02, 0x04, 0x08, 0x10, 0x1F],
    "0": [0x0E, 0x11, 0x13, 0x15, 0x19, 0x11, 0x0E],
    "1": [0x04, 0x0C, 0x04, 0x04, 0x04, 0x04, 0x0E],
    "2": [0x0E, 0x11, 0x01, 0x02, 0x04, 0x08, 0x1F],
    "3": [0x1F, 0x02, 0x04, 0x02, 0x01, 0x11, 0x0E],
    "4": [0x02, 0x06, 0x0A, 0x12, 0x1F, 0x02, 0x02],
    "5": [0x1F, 0x10, 0x1E, 0x01, 0x01, 0x11, 0x0E],
    "6": [0x06, 0x08, 0x10, 0x1E, 0x11, 0x11, 0x0E],
    "7": [0x1F, 0x01, 0x02, 0x04, 0x08, 0x08, 0x08],
    "8": [0x0E, 0x11, 0x11, 0x0E, 0x11, 0x11, 0x0E],
    "9": [0x0E, 0x11, 0x11, 0x0F, 0x01, 0x02, 0x0C],
    ".": [0, 0, 0, 0, 0, 0x0C, 0x0C],
    ",": [0, 0, 0, 0, 0x0C, 0x04, 0x08],
    "-": [0, 0, 0, 0x1F, 0, 0, 0],
    ":": [0, 0x0C, 0x0C, 0, 0x0C, 0x0C, 0],
    "/": [0x01, 0x01, 0x02, 0x04, 0x08, 0x10, 0x10],
    "(": [0x02, 0x04, 0x08, 0x08, 0x08, 0x04, 0x02],
    ")": [0x08, 0x04, 0x02, 0x02, 0x02, 0x04, 0x08],
    "²": [0x1C, 0x04, 0x1C, 0x10, 0x1C, 0x00, 0x00],
    "→": [0x00, 0x04, 0x02, 0x1F, 0x02, 0x04, 0x00],
}


# -- quantisation ------------------------------------------------------------
def _median_cut(colours: list[RGB], counts: list[int], want: int) -> list[RGB]:
    boxes = [list(range(len(colours)))]
    while len(boxes) < want:
        target, spread = -1, -1.0
        for i, box in enumerate(boxes):
            if len(box) < 2:
                continue
            for ch in range(3):
                vals = [colours[j][ch] for j in box]
                s = max(vals) - min(vals)
                if s > spread:
                    spread, target = s, i
        if target < 0 or spread <= 0:
            break
        box = boxes.pop(target)
        ch = max(range(3), key=lambda c: max(colours[j][c] for j in box) - min(colours[j][c] for j in box))
        box.sort(key=lambda j: colours[j][ch])
        half = len(box) // 2
        boxes.append(box[:half])
        boxes.append(box[half:])

    palette: list[RGB] = []
    for box in boxes:
        total = sum(counts[j] for j in box) or 1
        palette.append(
            (
                sum(colours[j][0] * counts[j] for j in box) // total,
                sum(colours[j][1] * counts[j] for j in box) // total,
                sum(colours[j][2] * counts[j] for j in box) // total,
            )
        )
    return palette or [(0, 0, 0)]


def quantise(frames: list[Canvas], max_colours: int = 256) -> tuple[list[RGB], list[bytes]]:
    """One global palette across all frames -- GIF wants that anyway."""
    hist: dict[RGB, int] = {}
    for f in frames:
        buf = f.buf
        for i in range(0, len(buf), 3):
            c = (buf[i], buf[i + 1], buf[i + 2])
            hist[c] = hist.get(c, 0) + 1

    uniq = list(hist)
    if len(uniq) <= max_colours:
        palette = uniq
        lookup = {c: i for i, c in enumerate(palette)}
    else:
        palette = _median_cut(uniq, [hist[c] for c in uniq], max_colours)
        lookup = {}

    indexed: list[bytes] = []
    for f in frames:
        buf = f.buf
        out = bytearray(f.w * f.h)
        for i in range(0, len(buf), 3):
            c = (buf[i], buf[i + 1], buf[i + 2])
            idx = lookup.get(c)
            if idx is None:
                idx = min(
                    range(len(palette)),
                    key=lambda k: (palette[k][0] - c[0]) ** 2
                    + (palette[k][1] - c[1]) ** 2
                    + (palette[k][2] - c[2]) ** 2,
                )
                lookup[c] = idx
            out[i // 3] = idx
        indexed.append(bytes(out))
    return palette, indexed


# -- GIF ---------------------------------------------------------------------
class _BitWriter:
    def __init__(self) -> None:
        self.out = bytearray()
        self.acc = 0
        self.nbits = 0

    def write(self, code: int, width: int) -> None:
        self.acc |= code << self.nbits
        self.nbits += width
        while self.nbits >= 8:
            self.out.append(self.acc & 0xFF)
            self.acc >>= 8
            self.nbits -= 8

    def flush(self) -> bytes:
        if self.nbits:
            self.out.append(self.acc & 0xFF)
            self.acc = 0
            self.nbits = 0
        return bytes(self.out)


def lzw_encode(data: bytes, min_code_size: int = 8) -> bytes:
    clear_code = 1 << min_code_size
    end_code = clear_code + 1
    writer = _BitWriter()

    table: dict[bytes, int] = {bytes([i]): i for i in range(clear_code)}
    next_code = end_code + 1
    code_width = min_code_size + 1

    writer.write(clear_code, code_width)
    if not data:
        writer.write(end_code, code_width)
        return writer.flush()

    prefix = data[0:1]
    for byte in data[1:]:
        candidate = prefix + bytes([byte])
        if candidate in table:
            prefix = candidate
            continue
        writer.write(table[prefix], code_width)
        table[candidate] = next_code
        next_code += 1
        if next_code > (1 << code_width):
            if code_width < 12:
                code_width += 1
            else:
                writer.write(clear_code, code_width)
                table = {bytes([i]): i for i in range(clear_code)}
                next_code = end_code + 1
                code_width = min_code_size + 1
        prefix = bytes([byte])

    writer.write(table[prefix], code_width)
    writer.write(end_code, code_width)
    return writer.flush()


def _sub_blocks(data: bytes) -> bytes:
    out = bytearray()
    for i in range(0, len(data), 255):
        chunk = data[i : i + 255]
        out.append(len(chunk))
        out += chunk
    out.append(0)
    return bytes(out)


def write_gif(
    path: str,
    frames: list[Canvas],
    delays_cs: Iterable[int],
    loop: int = 0,
    max_colours: int = 256,
) -> None:
    if not frames:
        raise ValueError("no frames to write")
    palette, indexed = quantise(frames, max_colours)
    w, h = frames[0].w, frames[0].h

    size = 1
    while (1 << size) < max(2, len(palette)):
        size += 1
    table_len = 1 << size
    table = bytearray()
    for i in range(table_len):
        table += bytes(palette[i] if i < len(palette) else (0, 0, 0))

    out = bytearray(b"GIF89a")
    out += w.to_bytes(2, "little") + h.to_bytes(2, "little")
    out += bytes([0xF0 | (size - 1), 0, 0])
    out += table
    out += b"\x21\xff\x0bNETSCAPE2.0\x03\x01" + loop.to_bytes(2, "little") + b"\x00"

    delays = list(delays_cs)
    for i, data in enumerate(indexed):
        delay = delays[i] if i < len(delays) else (delays[-1] if delays else 8)
        out += b"\x21\xf9\x04\x04" + int(delay).to_bytes(2, "little") + b"\x00\x00"
        out += b"\x2c" + (0).to_bytes(2, "little") + (0).to_bytes(2, "little")
        out += w.to_bytes(2, "little") + h.to_bytes(2, "little") + b"\x00"
        out += bytes([8])
        out += _sub_blocks(lzw_encode(data, 8))
    out += b"\x3b"

    with open(path, "wb") as fh:
        fh.write(bytes(out))
