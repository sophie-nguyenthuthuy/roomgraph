#!/usr/bin/env python3
"""Generate synthetic CAD-exported floor plan PDFs.

These are *synthetic* -- written by this script, not exported from AutoCAD or
Revit. They imitate the structure real vector exports have (paired wall faces,
optional-content layers, bezier door swings, dimension strings) so the pipeline
is exercised end to end and every fixture has known ground truth.

Real-exporter behaviour still needs real files; see docs/LIMITATIONS.md.

    python examples/make_fixtures.py [outdir]
"""

from __future__ import annotations

import json
import math
import os
import sys
import zlib

MM_PER_PT = 25.4 / 72.0


class PlanWriter:
    """Draws millimetre-space geometry into a scaled PDF page."""

    def __init__(self, width_mm: float, height_mm: float, scale: int = 50, margin_mm: float = 900):
        self.scale = scale
        self.margin = margin_mm
        self.width_mm = width_mm + 2 * margin_mm
        self.height_mm = height_mm + 2 * margin_mm
        self.page_w = self._pt(self.width_mm)
        self.page_h = self._pt(self.height_mm)
        self.ops: list[str] = []
        self.layers: list[str] = []
        self._layer_open = False

    def _pt(self, mm: float) -> float:
        return mm / self.scale / MM_PER_PT

    def x(self, mm: float) -> float:
        return self._pt(mm + self.margin)

    def y(self, mm: float) -> float:
        return self._pt(mm + self.margin)

    # -- layers ------------------------------------------------------------
    def layer(self, name: str, width_pt: float = 0.5, gray: float = 0.0) -> None:
        if self._layer_open:
            self.ops.append("EMC")
        if name not in self.layers:
            self.layers.append(name)
        idx = self.layers.index(name)
        self.ops.append(f"/OC /OC{idx} BDC")
        self.ops.append(f"{width_pt:.3f} w {gray:.2f} G")
        self._layer_open = True

    def close_layer(self) -> None:
        if self._layer_open:
            self.ops.append("EMC")
            self._layer_open = False

    # -- primitives --------------------------------------------------------
    def line(self, x1: float, y1: float, x2: float, y2: float) -> None:
        self.ops.append(
            f"{self.x(x1):.4f} {self.y(y1):.4f} m {self.x(x2):.4f} {self.y(y2):.4f} l S"
        )

    def polyline(self, pts: list[tuple[float, float]], close: bool = False) -> None:
        if len(pts) < 2:
            return
        cmd = [f"{self.x(pts[0][0]):.4f} {self.y(pts[0][1]):.4f} m"]
        for px, py in pts[1:]:
            cmd.append(f"{self.x(px):.4f} {self.y(py):.4f} l")
        cmd.append("h S" if close else "S")
        self.ops.append(" ".join(cmd))

    def arc(self, cx: float, cy: float, r: float, a0: float, a1: float) -> None:
        """Bezier-approximated arc, split into <=90 degree spans (as CAD exports do)."""
        span = a1 - a0
        n = max(1, int(math.ceil(abs(span) / (math.pi / 2))))
        step = span / n
        sx = cx + r * math.cos(a0)
        sy = cy + r * math.sin(a0)
        cmd = [f"{self.x(sx):.4f} {self.y(sy):.4f} m"]
        for i in range(n):
            t0 = a0 + i * step
            t1 = t0 + step
            k = 4.0 / 3.0 * math.tan((t1 - t0) / 4.0)
            p0 = (cx + r * math.cos(t0), cy + r * math.sin(t0))
            p3 = (cx + r * math.cos(t1), cy + r * math.sin(t1))
            c1 = (p0[0] - k * r * math.sin(t0), p0[1] + k * r * math.cos(t0))
            c2 = (p3[0] + k * r * math.sin(t1), p3[1] - k * r * math.cos(t1))
            cmd.append(
                f"{self.x(c1[0]):.4f} {self.y(c1[1]):.4f} "
                f"{self.x(c2[0]):.4f} {self.y(c2[1]):.4f} "
                f"{self.x(p3[0]):.4f} {self.y(p3[1]):.4f} c"
            )
        cmd.append("S")
        self.ops.append(" ".join(cmd))

    def text(self, s: str, x: float, y: float, size_pt: float = 7.0, rot: float = 0.0) -> None:
        esc = s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        c, sn = math.cos(rot), math.sin(rot)
        self.ops.append(
            f"BT /F1 {size_pt:.2f} Tf {c:.5f} {sn:.5f} {-sn:.5f} {c:.5f} "
            f"{self.x(x):.4f} {self.y(y):.4f} Tm ({esc}) Tj ET"
        )

    # -- building blocks ---------------------------------------------------
    def wall(
        self,
        p1: tuple[float, float],
        p2: tuple[float, float],
        thickness: float,
        openings: list[tuple[float, float]] | None = None,
    ) -> None:
        """Two parallel faces around a centreline, with gaps cut for openings.

        `openings` are (centre_distance_along_wall, width) pairs.
        """
        (x1, y1), (x2, y2) = p1, p2
        dx, dy = x2 - x1, y2 - y1
        ln = math.hypot(dx, dy)
        if ln < 1e-6:
            return
        ux, uy = dx / ln, dy / ln
        nx, ny = -uy * thickness / 2.0, ux * thickness / 2.0

        cuts = sorted(openings or [], key=lambda o: o[0])
        spans: list[tuple[float, float]] = []
        cursor = 0.0
        for centre, width in cuts:
            a, b = centre - width / 2.0, centre + width / 2.0
            if a > cursor:
                spans.append((cursor, a))
            cursor = max(cursor, b)
        if cursor < ln:
            spans.append((cursor, ln))

        for side in (1, -1):
            ox, oy = nx * side, ny * side
            for s0, s1 in spans:
                self.line(
                    x1 + ux * s0 + ox, y1 + uy * s0 + oy,
                    x1 + ux * s1 + ox, y1 + uy * s1 + oy,
                )
        # Cap the exposed jamb at each opening, as CAD does.
        for centre, width in cuts:
            for end in (centre - width / 2.0, centre + width / 2.0):
                if 0 < end < ln:
                    self.line(
                        x1 + ux * end + nx, y1 + uy * end + ny,
                        x1 + ux * end - nx, y1 + uy * end - ny,
                    )

    def door_swing(
        self,
        hinge: tuple[float, float],
        width: float,
        open_angle: float,
        swing_deg: float = 90.0,
    ) -> None:
        """Leaf line plus swing arc -- the canonical single-leaf door symbol."""
        a0 = math.radians(open_angle)
        leaf_end = (hinge[0] + width * math.cos(a0), hinge[1] + width * math.sin(a0))
        self.line(hinge[0], hinge[1], leaf_end[0], leaf_end[1])
        self.arc(hinge[0], hinge[1], width, a0, a0 - math.radians(swing_deg))

    def window(
        self,
        p1: tuple[float, float],
        p2: tuple[float, float],
        thickness: float,
    ) -> None:
        """Three parallel lines spanning the opening: two jamb faces plus the glass."""
        (x1, y1), (x2, y2) = p1, p2
        dx, dy = x2 - x1, y2 - y1
        ln = math.hypot(dx, dy)
        ux, uy = dx / ln, dy / ln
        nx, ny = -uy, ux
        for off in (thickness / 2.0, 0.0, -thickness / 2.0):
            self.line(x1 + nx * off, y1 + ny * off, x2 + nx * off, y2 + ny * off)

    def dimension(
        self,
        p1: tuple[float, float],
        p2: tuple[float, float],
        offset: float,
    ) -> None:
        """Dimension line with its value as text -- this is what calibrates scale."""
        (x1, y1), (x2, y2) = p1, p2
        dx, dy = x2 - x1, y2 - y1
        ln = math.hypot(dx, dy)
        ux, uy = dx / ln, dy / ln
        nx, ny = -uy * offset, ux * offset
        a = (x1 + nx, y1 + ny)
        b = (x2 + nx, y2 + ny)
        self.line(a[0], a[1], b[0], b[1])
        self.line(x1, y1, a[0], a[1])
        self.line(x2, y2, b[0], b[1])
        # Real CAD rotates dimension text to run along its dimension line.
        rot = math.atan2(uy, ux)
        if rot > math.pi / 2 or rot <= -math.pi / 2:
            rot += math.pi
        mid = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
        px, py = -math.sin(rot), math.cos(rot)
        self.text(f"{int(round(ln))}", mid[0] - ux * 220 + px * 90, mid[1] - uy * 220 + py * 90, 6.0, rot)

    # -- output ------------------------------------------------------------
    def save(self, path: str, title: str = "") -> None:
        self.close_layer()
        content = "\n".join(self.ops).encode("latin-1", "replace")
        compressed = zlib.compress(content, 9)

        objects: list[bytes] = []

        def add(body: bytes) -> int:
            objects.append(body)
            return len(objects)

        first_ocg = 7
        ocg_refs = " ".join(f"{first_ocg + i} 0 R" for i in range(len(self.layers)))
        add(
            b"<< /Type /Catalog /Pages 2 0 R /OCProperties << /OCGs [" + ocg_refs.encode()
            + b"] /D << /Order [" + ocg_refs.encode() + b"] >> >> >>"
        )
        add(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
        props = " ".join(f"/OC{i} {first_ocg + i} 0 R" for i in range(len(self.layers)))
        add(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {self.page_w:.3f} {self.page_h:.3f}] "
            f"/Resources << /Font << /F1 5 0 R >> /Properties << {props} >> >> "
            f"/Contents 4 0 R >>".encode()
        )
        add(
            b"<< /Length " + str(len(compressed)).encode() + b" /Filter /FlateDecode >>\nstream\n"
            + compressed + b"\nendstream"
        )
        add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
        add(b"<< /Type /Info /Title (" + title.encode("latin-1", "replace") + b") >>")
        for name in self.layers:
            add(b"<< /Type /OCG /Name (" + name.encode("latin-1", "replace") + b") >>")

        out = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
        offsets = [0]
        for i, body in enumerate(objects, start=1):
            offsets.append(len(out))
            out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
        xref_pos = len(out)
        n = len(objects) + 1
        out += f"xref\n0 {n}\n".encode()
        out += b"0000000000 65535 f \n"
        for off in offsets[1:]:
            out += f"{off:010d} 00000 n \n".encode()
        out += (
            f"trailer\n<< /Size {n} /Root 1 0 R /Info 6 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n"
        ).encode()

        with open(path, "wb") as fh:
            fh.write(bytes(out))


# ---------------------------------------------------------------------------
# Fixture 1: two-bedroom apartment, orthogonal, three rooms
# ---------------------------------------------------------------------------
def apartment(outdir: str) -> dict:
    W, H = 9600.0, 7200.0
    EXT, INT = 220.0, 110.0
    p = PlanWriter(W, H, scale=50)

    p.layer("A-WALL", width_pt=0.7)
    p.wall((0, 0), (W, 0), EXT, openings=[(2400, 1000)])          # entry door
    p.wall((W, 0), (W, H), EXT)
    p.wall((W, H), (0, H), EXT, openings=[(2400, 1200)])          # window (from x=W)
    p.wall((0, H), (0, 0), EXT, openings=[(3600, 1500)])          # window (from y=H)
    p.wall((4800, 0), (4800, H), INT, openings=[(1800, 800), (5400, 900)])
    p.wall((4800, 3600), (W, 3600), INT)

    p.layer("A-DOOR", width_pt=0.35)
    p.door_swing((1900, 0), 1000, 90.0)                            # entry, swings in
    p.door_swing((4800, 1400), 800, 0.0)                           # to kitchen
    p.door_swing((4800, 5850), 900, 180.0, swing_deg=-90.0)        # to bedroom

    p.layer("A-GLAZ", width_pt=0.35)
    p.window((W - 1800, H), (W - 3000, H), EXT)
    p.window((0, 2850), (0, 4350), EXT)

    p.layer("A-FURN", width_pt=0.25, gray=0.45)
    p.polyline([(600, 600), (2400, 600), (2400, 1500), (600, 1500)], close=True)   # sofa
    p.polyline([(5400, 4400), (8000, 4400), (8000, 6400), (5400, 6400)], close=True)  # bed

    p.layer("A-ANNO", width_pt=0.25)
    p.text("PHONG KHACH", 1500, 4200, 9.0)
    p.text("34.6 m2", 1900, 3700, 7.0)
    p.text("PHONG NGU", 6100, 5600, 9.0)
    p.text("17.3 m2", 6500, 5100, 7.0)
    p.text("BEP", 6900, 1900, 9.0)
    p.text("17.3 m2", 6400, 1400, 7.0)

    p.layer("A-DIMS", width_pt=0.25)
    p.dimension((0, 0), (W, 0), -700)
    p.dimension((W, 0), (W, H), 700)

    path = os.path.join(outdir, "apartment.pdf")
    p.save(path, title="Apartment 2BR - scale 1:50")
    return {
        "file": "apartment.pdf",
        "scale": 50,
        "rooms": [
            {"name": "PHONG KHACH", "area_gross_m2": round(4.8 * 7.2, 2)},
            {"name": "PHONG NGU", "area_gross_m2": round(4.8 * 3.6, 2)},
            {"name": "BEP", "area_gross_m2": round(4.8 * 3.6, 2)},
        ],
        "room_count": 3,
        "doors": 3,
        "windows": 2,
        "adjacency": [
            ["PHONG KHACH", "PHONG NGU", "door"],
            ["PHONG KHACH", "BEP", "door"],
            ["PHONG NGU", "BEP", "wall"],
        ],
    }


# ---------------------------------------------------------------------------
# Fixture 2: L-shaped studio -- non-convex room, centroid falls outside
# ---------------------------------------------------------------------------
def studio(outdir: str) -> dict:
    EXT, INT = 200.0, 100.0
    p = PlanWriter(8000.0, 6000.0, scale=50)

    p.layer("A-WALL", width_pt=0.7)
    outline = [(0, 0), (8000, 0), (8000, 6000), (3000, 6000), (3000, 2600), (0, 2600)]
    door_on = {0: [(4000, 900)]}
    for i in range(len(outline)):
        a, b = outline[i], outline[(i + 1) % len(outline)]
        p.wall(a, b, EXT, openings=door_on.get(i))
    p.wall((5200, 0), (5200, 2600), INT, openings=[(1300, 800)])
    p.wall((5200, 2600), (8000, 2600), INT)

    p.layer("A-DOOR", width_pt=0.35)
    p.door_swing((3550, 0), 900, 90.0)
    p.door_swing((5200, 900), 800, 0.0)

    p.layer("A-ANNO", width_pt=0.25)
    p.text("STUDIO", 1200, 1200, 9.0)
    p.text("WC", 6400, 1200, 9.0)

    p.layer("A-DIMS", width_pt=0.25)
    p.dimension((0, 0), (8000, 0), -700)

    path = os.path.join(outdir, "studio_lshape.pdf")
    p.save(path, title="Studio L-shape 1:50")
    return {
        "file": "studio_lshape.pdf",
        "scale": 50,
        "room_count": 2,
        "doors": 2,
        "windows": 0,
        "rooms": [{"name": "STUDIO", "area_gross_m2": 30.52}, {"name": "WC", "area_gross_m2": 7.28}],
        "notes": "L-shaped main space; centroid of the L falls outside the polygon",
    }


# ---------------------------------------------------------------------------
# Fixture 3: bay window -- a symbol whose geometry lives outside the wall
# ---------------------------------------------------------------------------
def bay_house(outdir: str) -> dict:
    W, H = 8000.0, 6000.0
    EXT, INT = 220.0, 110.0
    BAY_WIDTH, BAY_DEPTH, BAY_INSET = 2400.0, 700.0, 500.0
    p = PlanWriter(W, H + BAY_DEPTH, scale=50)

    p.layer("A-WALL", width_pt=0.7)
    p.wall((0, 0), (W, 0), EXT, openings=[(1200, 900)])
    p.wall((W, 0), (W, H), EXT)
    p.wall((W, H), (0, H), EXT, openings=[(2800, BAY_WIDTH)])
    p.wall((0, H), (0, 0), EXT)
    p.wall((4600, 0), (4600, H), INT, openings=[(3000, 800)])

    p.layer("A-DOOR", width_pt=0.35)
    p.door_swing((750, 0), 900, 90.0)
    p.door_swing((4600, 2600), 800, 0.0)

    # The bay projects outward through the north wall. Its opening is measured
    # from (W, H) back toward the origin, so the centre lands at x = W - 2800.
    p.layer("A-GLAZ", width_pt=0.35)
    cx = W - 2800.0
    half = BAY_WIDTH / 2.0
    p.polyline(
        [
            (cx - half, H),
            (cx - half + BAY_INSET, H + BAY_DEPTH),
            (cx + half - BAY_INSET, H + BAY_DEPTH),
            (cx + half, H),
        ]
    )

    p.layer("A-ANNO", width_pt=0.25)
    p.text("PHONG KHACH", 1500, 3000, 9.0)
    p.text("PHONG NGU", 5600, 1500, 9.0)

    p.layer("A-DIMS", width_pt=0.25)
    p.dimension((0, 0), (W, 0), -700)

    path = os.path.join(outdir, "bay_house.pdf")
    p.save(path, title="Bay window house 1:50")
    return {
        "file": "bay_house.pdf",
        "scale": 50,
        "room_count": 2,
        "doors": 2,
        "windows": 1,
        "bay": {
            "symbol": "window_bay",
            "style": "canted",
            "facets": 3,
            "width_mm": BAY_WIDTH,
            "projection_mm": BAY_DEPTH,
        },
        "notes": "bay window geometry sits outside the wall line, unlike flat glazing",
    }


def main() -> int:
    outdir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "plans")
    os.makedirs(outdir, exist_ok=True)
    truth = [apartment(outdir), studio(outdir), bay_house(outdir)]
    with open(os.path.join(outdir, "ground_truth.json"), "w") as fh:
        json.dump(truth, fh, indent=2)
    for t in truth:
        print(f"wrote {os.path.join(outdir, t['file'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
