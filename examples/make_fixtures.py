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

    def solid(self, pts: list[tuple[float, float]]) -> None:
        """A filled outline -- poche, as structure is drawn."""
        if len(pts) < 3:
            return
        cmd = [f"{self.x(pts[0][0]):.4f} {self.y(pts[0][1]):.4f} m"]
        for px, py in pts[1:]:
            cmd.append(f"{self.x(px):.4f} {self.y(py):.4f} l")
        cmd.append("h f")
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


# ---------------------------------------------------------------------------
# Fixture 4: corner window -- the corner itself is missing from the drawing
# ---------------------------------------------------------------------------
def corner_house(outdir: str) -> dict:
    W, H, EXT = 7000.0, 5000.0, 220.0
    LEG = 1600.0  # glazed length taken out of each wall at the corner
    p = PlanWriter(W, H, scale=50)

    p.layer("A-WALL", width_pt=0.7)
    p.wall((0, 0), (W, 0), EXT, openings=[(1200, 900)])
    p.wall((W, 0), (W, H), EXT)
    # Both walls stop short of the top-left corner: there is no corner to find.
    p.wall((W, H), (LEG, H), EXT)
    p.wall((0, H - LEG), (0, 0), EXT)

    p.layer("A-DOOR", width_pt=0.35)
    p.door_swing((750, 0), 900, 90.0)

    p.layer("A-GLAZ", width_pt=0.35)
    for off in (EXT / 2.0, -EXT / 2.0):
        p.polyline([(LEG, H + off), (-off, H + off), (-off, H - LEG)])

    p.layer("A-ANNO", width_pt=0.25)
    p.text("PHONG KHACH", 2000, 2200, 9.0)

    p.layer("A-DIMS", width_pt=0.25)
    p.dimension((0, 0), (W, 0), -700)

    path = os.path.join(outdir, "corner_window.pdf")
    p.save(path, title="Corner window 1:50")
    return {
        "file": "corner_window.pdf",
        "scale": 50,
        "room_count": 1,
        "doors": 1,
        "windows": 2,
        "rooms": [{"name": "PHONG KHACH", "area_gross_m2": round(W * H / 1e6, 2)}],
        "corner_window": {
            "symbol": "window_corner",
            "openings": 2,
            "leg_mm": LEG,
            "note": "one opening per wall; without corner bridging the room does not close",
        },
        "notes": "the corner is absent from the drawing and must be reconstructed",
    }


# ---------------------------------------------------------------------------
# Fixture 5: folding door on a diagonal wall -- the only non-rectilinear plan
# ---------------------------------------------------------------------------
def folding_door(outdir: str) -> dict:
    W, H = 8000.0, 6000.0
    EXT, INT = 220.0, 110.0
    LEAVES, FOLD_W, FOLD_DEPTH = 4, 1800.0, 340.0
    p = PlanWriter(W, H, scale=50)

    p.layer("A-WALL", width_pt=0.7)
    p.wall((0, 0), (W, 0), EXT, openings=[(1200, 900)])
    p.wall((W, 0), (W, H), EXT)
    p.wall((W, H), (0, H), EXT)
    p.wall((0, H), (0, 0), EXT)

    # A diagonal partition, so the local frame is exercised at an angle rather
    # than only on axis-aligned walls.
    a, b = (2000.0, 0.0), (6000.0, H)
    length = math.hypot(b[0] - a[0], b[1] - a[1])
    p.wall(a, b, INT, openings=[(length / 2.0, FOLD_W)])

    p.layer("A-DOOR", width_pt=0.35)
    p.door_swing((1550, 0), 900, 90.0)

    ux, uy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
    nx, ny = -uy, ux
    t0 = length / 2.0 - FOLD_W / 2.0
    zigzag = []
    for i in range(LEAVES + 1):
        t = t0 + FOLD_W * i / LEAVES
        off = 0.0 if i % 2 == 0 else FOLD_DEPTH
        zigzag.append((a[0] + ux * t + nx * off, a[1] + uy * t + ny * off))
    p.polyline(zigzag)

    p.layer("A-ANNO", width_pt=0.25)
    p.text("PHONG KHACH", 900, 3000, 9.0)
    p.text("BEP", 6400, 2500, 9.0)

    p.layer("A-DIMS", width_pt=0.25)
    p.dimension((0, 0), (W, 0), -700)

    path = os.path.join(outdir, "folding_door.pdf")
    p.save(path, title="Folding door on a diagonal wall 1:50")
    half = round(W * H / 2e6, 2)
    return {
        "file": "folding_door.pdf",
        "scale": 50,
        "room_count": 2,
        "doors": 2,
        "windows": 0,
        "rooms": [
            {"name": "PHONG KHACH", "area_gross_m2": half},
            {"name": "BEP", "area_gross_m2": half},
        ],
        "folding_door": {
            "symbol": "door_folding",
            "panels": LEAVES,
            "width_mm": FOLD_W,
            # The drawn leaf is the panel itself, so its length is the
            # hypotenuse of the advance along the wall and the fold depth --
            # the panels sum to more than the opening precisely because they
            # are folded.
            "leaf_width_mm": round(math.hypot(FOLD_W / LEAVES, FOLD_DEPTH), 1),
        },
        "notes": "diagonal partition: the only fixture that is not axis aligned",
    }


# ---------------------------------------------------------------------------
# Fixture 6: revolving door in a lobby -- leaves radiating from a hub
# ---------------------------------------------------------------------------
def revolving_lobby(outdir: str) -> dict:
    W, H = 9000.0, 6000.0
    EXT, INT = 300.0, 110.0
    DRUM, LEAVES = 2000.0, 4
    p = PlanWriter(W, H, scale=50)

    p.layer("A-WALL", width_pt=0.7)
    p.wall((0, 0), (W, 0), EXT, openings=[(4500, DRUM)])
    p.wall((W, 0), (W, H), EXT)
    p.wall((W, H), (0, H), EXT)
    p.wall((0, H), (0, 0), EXT)
    p.wall((6200, 0), (6200, H), INT, openings=[(3000, 1000)])

    p.layer("A-DOOR", width_pt=0.35)
    cx, cy, r = 4500.0, 0.0, DRUM / 2.0
    p.arc(cx, cy, r, 0.0, 2 * math.pi)  # the drum
    for k in range(LEAVES):
        a = math.radians(45.0 + 360.0 * k / LEAVES)
        p.line(cx, cy, cx + r * math.cos(a), cy + r * math.sin(a))
    p.door_swing((6200, 2500), 1000, 180.0)  # hinged on the lower jamb

    p.layer("A-ANNO", width_pt=0.25)
    p.text("SANH", 3000, 3000, 9.0)
    p.text("VAN PHONG", 7000, 3000, 9.0)

    p.layer("A-DIMS", width_pt=0.25)
    p.dimension((0, 0), (W, 0), -800)

    path = os.path.join(outdir, "revolving_lobby.pdf")
    p.save(path, title="Revolving door lobby 1:50")
    return {
        "file": "revolving_lobby.pdf",
        "scale": 50,
        "room_count": 2,
        "doors": 2,
        "windows": 0,
        "revolving_door": {
            "symbol": "door_revolving",
            "panels": LEAVES,
            "drum_diameter_mm": DRUM,
            "drum_drawn": True,
        },
        "notes": "hub at the opening centre, unlike a swing door hinged at a jamb",
    }


# ---------------------------------------------------------------------------
# Fixture 7: commercial unit -- curtain walling, roller shutter, lift core
# ---------------------------------------------------------------------------
def commercial_unit(outdir: str) -> dict:
    W, H = 12000.0, 8000.0
    EXT, INT = 250.0, 150.0
    CW_RUN, CW_MULLIONS = 6000.0, 4
    SHUTTER = 3000.0
    CAR_L, CAR_W = 1600.0, 1400.0
    p = PlanWriter(W, H, scale=100)

    p.layer("A-WALL", width_pt=0.7)
    p.wall((0, 0), (W, 0), EXT, openings=[(4000, CW_RUN)])
    p.wall((W, 0), (W, H), EXT, openings=[(4000, SHUTTER)])
    p.wall((W, H), (0, H), EXT)
    p.wall((0, H), (0, 0), EXT)
    p.wall((3000, 5000), (3000, H), INT)
    p.wall((0, 5000), (3000, 5000), INT, openings=[(1500, 900)])

    p.layer("A-DOOR", width_pt=0.35)
    p.door_swing((1050, 5000), 900, -90.0)

    # Curtain walling: two glazing lines and mullions on a regular module.
    p.layer("A-GLAZ", width_pt=0.35)
    x0, x1 = 4000.0 - CW_RUN / 2.0, 4000.0 + CW_RUN / 2.0
    for off in (EXT / 2.0, -EXT / 2.0):
        p.line(x0, off, x1, off)
    module = CW_RUN / (CW_MULLIONS + 1)
    for i in range(1, CW_MULLIONS + 1):
        mx = x0 + module * i
        p.line(mx, EXT / 2.0, mx, -EXT / 2.0)

    # Roller shutter: a corrugated curtain across the side opening.
    p.layer("A-SHUT", width_pt=0.35)
    teeth = 20
    y0 = 4000.0 - SHUTTER / 2.0
    p.polyline(
        [(W + (45.0 if i % 2 else -45.0), y0 + SHUTTER * i / teeth) for i in range(teeth + 1)]
    )

    # Lift car: a crossed box in its own shaft.
    p.layer("A-LIFT", width_pt=0.35)
    lx, ly = 700.0, 5700.0
    p.polyline(
        [(lx, ly), (lx + CAR_L, ly), (lx + CAR_L, ly + CAR_W), (lx, ly + CAR_W)], close=True
    )
    p.line(lx, ly, lx + CAR_L, ly + CAR_W)
    p.line(lx + CAR_L, ly, lx, ly + CAR_W)

    p.layer("A-ANNO", width_pt=0.25)
    p.text("SANH", 6000, 2500, 9.0)
    p.text("THANG MAY", 900, 6600, 7.0)

    p.layer("A-DIMS", width_pt=0.25)
    p.dimension((0, 0), (W, 0), -900)

    path = os.path.join(outdir, "commercial_unit.pdf")
    p.save(path, title="Commercial unit 1:100")
    return {
        "file": "commercial_unit.pdf",
        "scale": 100,
        "room_count": 2,
        "curtain_wall": {"symbol": "curtain_wall", "run_mm": CW_RUN, "mullions": CW_MULLIONS},
        "roller_shutter": {"symbol": "door_roller", "clear_width_mm": SHUTTER},
        "lift": {"symbol": "lift", "car_mm": [CAR_L, CAR_W]},
        "notes": "a 6 m glazed run only survives because MAX_OPENING allows it",
    }


# ---------------------------------------------------------------------------
# Fixture 8: services -- sanitary fittings and a spiral stair
# ---------------------------------------------------------------------------
def services(outdir: str) -> dict:
    W, H = 6000.0, 5000.0
    EXT, INT = 220.0, 110.0
    TREADS, RADIUS = 12, 900.0
    p = PlanWriter(W, H, scale=50)

    p.layer("A-WALL", width_pt=0.7)
    p.wall((0, 0), (W, 0), EXT, openings=[(4300, 900)])
    p.wall((W, 0), (W, H), EXT)
    p.wall((W, H), (0, H), EXT)
    p.wall((0, H), (0, 0), EXT)
    p.wall((2600, 0), (2600, H), INT, openings=[(2500, 800)])

    p.layer("A-DOOR", width_pt=0.35)
    p.door_swing((3850, 0), 900, 90.0)
    p.door_swing((2600, 2100), 800, 0.0)

    # Sanitary fittings in the left room.
    p.layer("A-SANR", width_pt=0.3)
    for x, y, w, h in (
        (150, 150, 1700, 750),      # bath
        (1700, 1100, 700, 400),     # wc, clear of the partition at x=2600
        (300, 1300, 650, 480),      # basin
    ):
        p.polyline([(x, y), (x + w, y), (x + w, y + h), (x, y + h)], close=True)

    # Spiral stair in the right room.
    p.layer("A-STRS", width_pt=0.3)
    cx, cy = 4300.0, 3200.0
    for i in range(TREADS):
        a = 2 * math.pi * i / TREADS
        p.line(cx, cy, cx + RADIUS * math.cos(a), cy + RADIUS * math.sin(a))
    p.arc(cx, cy, RADIUS, 0.0, 2 * math.pi)

    p.layer("A-ANNO", width_pt=0.25)
    p.text("WC", 1200, 3000, 9.0)
    p.text("CAU THANG", 3600, 1200, 8.0)

    p.layer("A-DIMS", width_pt=0.25)
    p.dimension((0, 0), (W, 0), -700)

    path = os.path.join(outdir, "services.pdf")
    p.save(path, title="Services 1:50")
    return {
        "file": "services.pdf",
        "scale": 50,
        "room_count": 2,
        "sanitary": {"symbol": "sanitary", "fittings": ["basin", "bath", "wc"]},
        "spiral": {"symbol": "stairs_spiral", "treads": TREADS, "radius_mm": RADIUS},
        "notes": "room-scope symbols; both rooms report independently",
    }


# ---------------------------------------------------------------------------
# Fixture 9: fitted flat -- kitchen run, columns, accessible WC
# ---------------------------------------------------------------------------
def fitted_flat(outdir: str) -> dict:
    W, H = 8000.0, 6000.0
    EXT, INT = 220.0, 110.0
    p = PlanWriter(W, H, scale=50)

    p.layer("A-WALL", width_pt=0.7)
    p.wall((0, 0), (W, 0), EXT, openings=[(1200, 900)])
    p.wall((W, 0), (W, H), EXT)
    p.wall((W, H), (0, H), EXT)
    p.wall((0, H), (0, 0), EXT)
    p.wall((4000, 0), (4000, H), INT, openings=[(1500, 900), (4500, 900)])
    p.wall((4000, 3000), (W, 3000), INT, openings=[(2000, 800)])

    p.layer("A-DOOR", width_pt=0.35)
    p.door_swing((750, 0), 900, 90.0)
    p.door_swing((4000, 1050), 900, 0.0)
    p.door_swing((4000, 4050), 900, 0.0)
    p.door_swing((5600, 3000), 800, 90.0)

    # Kitchen: a run of 600 deep units along the north wall of the left room.
    p.layer("A-FURN", width_pt=0.3)
    x = 300.0
    for length in (1800.0, 600.0, 600.0, 700.0):
        p.polyline(
            [(x, H - 900), (x + length, H - 900), (x + length, H - 300), (x, H - 300)],
            close=True,
        )
        x += length

    # Two columns in the living room, one poched.
    p.layer("S-COLS", width_pt=0.4)
    p.solid([(5200, 4200), (5700, 4200), (5700, 4700), (5200, 4700)])
    p.polyline([(7000, 4200), (7500, 4200), (7500, 4700), (7000, 4700)], close=True)

    # Accessible WC: a clear 1500 turning circle, with the pan outside it.
    p.layer("A-SANR", width_pt=0.3)
    p.arc(5600.0, 1500.0, 750.0, 0.0, 2 * math.pi)
    p.polyline([(7100, 300), (7800, 300), (7800, 700), (7100, 700)], close=True)

    p.layer("A-ANNO", width_pt=0.25)
    p.text("BEP", 1500, 2500, 9.0)
    p.text("PHONG KHACH", 4600, 5400, 9.0)
    p.text("WC", 4400, 800, 9.0)

    p.layer("A-DIMS", width_pt=0.25)
    p.dimension((0, 0), (W, 0), -700)

    path = os.path.join(outdir, "fitted_flat.pdf")
    p.save(path, title="Fitted flat 1:50")
    return {
        "file": "fitted_flat.pdf",
        "scale": 50,
        "room_count": 3,
        "kitchen": {"symbol": "kitchen", "units": 4, "depth_mm": 600.0},
        "columns": {"symbol": "column", "columns": 2, "filled": 1},
        "turning_circle": {"symbol": "turning_circle", "diameter_mm": 1500.0},
        "notes": "one column is poched, which exercises the fill channel end to end",
    }


# ---------------------------------------------------------------------------
# Fixture 10: transport hall -- escalator, ramp, fire shutter
# ---------------------------------------------------------------------------
def transport_hall(outdir: str) -> dict:
    W, H = 16000.0, 20000.0
    EXT = 300.0
    STEPS, GOING, ESC_W = 24, 400.0, 1200.0
    SHUTTER = 3000.0
    p = PlanWriter(W, H, scale=100)

    p.layer("A-WALL", width_pt=0.7)
    p.wall((0, 0), (W, 0), EXT, openings=[(4000, SHUTTER)])
    p.wall((W, 0), (W, H), EXT)
    p.wall((W, H), (0, H), EXT)
    p.wall((0, H), (0, 0), EXT)

    # Fire shutter: roller geometry, but on a fire layer.
    p.layer("A-FIRE-SHUT", width_pt=0.4)
    teeth = 24
    x0 = 4000.0 - SHUTTER / 2.0
    p.polyline(
        [(x0 + SHUTTER * i / teeth, 60.0 if i % 2 else -60.0) for i in range(teeth + 1)]
    )

    # Escalator: steps between two full length balustrades.
    p.layer("A-ESCL", width_pt=0.3)
    ex, ey = 2000.0, 4000.0
    for i in range(STEPS):
        p.line(ex, ey + GOING * i, ex + ESC_W, ey + GOING * i)
    run = GOING * (STEPS - 1)
    p.line(ex, ey, ex, ey + run)
    p.line(ex + ESC_W, ey, ex + ESC_W, ey + run)

    # Ramp: a band with its gradient written on it, and no steps.
    p.layer("A-RAMP", width_pt=0.3)
    p.line(8000, 4000, 8000, 15000)
    p.line(10400, 4000, 10400, 15000)

    p.layer("A-ANNO", width_pt=0.25)
    p.text("SANH", 12000, 10000, 11.0)
    p.text("RAMP 1:12", 8400, 9500, 7.0)

    p.layer("A-DIMS", width_pt=0.25)
    p.dimension((0, 0), (W, 0), -1200)

    path = os.path.join(outdir, "transport_hall.pdf")
    p.save(path, title="Transport hall 1:100")
    return {
        "file": "transport_hall.pdf",
        "scale": 100,
        "room_count": 1,
        "escalator": {"symbol": "escalator", "steps": STEPS, "going_mm": GOING},
        "ramp": {"symbol": "ramp", "gradient": "1:12"},
        "fire_shutter": {"symbol": "door_fire_shutter", "clear_width_mm": SHUTTER},
        "notes": "escalator and ramp share one room; room features accumulate",
    }


# ---------------------------------------------------------------------------
# Fixture 11: dwelling -- bed and desk, planting, a dumbwaiter
# ---------------------------------------------------------------------------
def dwelling(outdir: str) -> dict:
    W, H = 9000.0, 7000.0
    EXT, INT = 220.0, 110.0
    p = PlanWriter(W, H, scale=50)

    p.layer("A-WALL", width_pt=0.7)
    p.wall((0, 0), (W, 0), EXT, openings=[(1200, 900)])
    p.wall((W, 0), (W, H), EXT)
    p.wall((W, H), (0, H), EXT)
    p.wall((0, H), (0, 0), EXT)
    p.wall((4500, 0), (4500, H), INT, openings=[(2000, 900), (5500, 900)])
    p.wall((4500, 4500), (W, 4500), INT, openings=[(2200, 800)])

    p.layer("A-DOOR", width_pt=0.35)
    p.door_swing((750, 0), 900, 90.0)
    p.door_swing((4500, 1550), 900, 0.0)
    p.door_swing((4500, 5050), 900, 0.0)
    p.door_swing((6300, 4500), 800, 90.0)

    p.layer("A-FURN", width_pt=0.3)
    p.polyline([(400, 400), (2400, 400), (2400, 1900), (400, 1900)], close=True)   # bed
    p.polyline([(400, 2600), (1800, 2600), (1800, 3300), (400, 3300)], close=True) # desk

    p.layer("L-PLNT-SHRB", width_pt=0.3)
    for cx, cy, r in ((6000.0, 5600.0, 700.0), (8000.0, 5600.0, 550.0)):
        p.polyline(
            [
                (
                    cx + r * (1 + 0.22 * math.cos(9 * 2 * math.pi * i / 72))
                    * math.cos(2 * math.pi * i / 72),
                    cy + r * (1 + 0.22 * math.cos(9 * 2 * math.pi * i / 72))
                    * math.sin(2 * math.pi * i / 72),
                )
                for i in range(72)
            ],
            close=True,
        )

    p.layer("A-LIFT", width_pt=0.35)
    dx, dy, ds = 5200.0, 500.0, 600.0
    p.polyline([(dx, dy), (dx + ds, dy), (dx + ds, dy + ds), (dx, dy + ds)], close=True)
    p.line(dx, dy, dx + ds, dy + ds)
    p.line(dx + ds, dy, dx, dy + ds)

    p.layer("A-ANNO", width_pt=0.25)
    p.text("PHONG NGU", 1500, 5000, 9.0)
    p.text("SAN VUON", 6200, 6400, 9.0)
    p.text("KHO", 7600, 2200, 9.0)

    p.layer("A-DIMS", width_pt=0.25)
    p.dimension((0, 0), (W, 0), -700)

    path = os.path.join(outdir, "dwelling.pdf")
    p.save(path, title="Dwelling 1:50")
    return {
        "file": "dwelling.pdf",
        "scale": 50,
        "room_count": 3,
        "furniture": {"symbol": "furniture_layout", "beds": 1, "items": ["bed_double", "desk"]},
        "planting": {"symbol": "planting", "canopies": 2},
        "dumbwaiter": {"symbol": "dumbwaiter", "car_mm": [600.0, 600.0]},
        "notes": "the desk is only claimed because the room is named as a bedroom",
    }


# ---------------------------------------------------------------------------
# Fixture 12: concourse -- travelator, fire equipment, parking bays
# ---------------------------------------------------------------------------
def concourse(outdir: str) -> dict:
    W, H = 24000.0, 16000.0
    EXT, INT = 300.0, 200.0
    RUN, BAND = 20000.0, 1400.0
    BAY_L, BAY_W, BAYS = 5000.0, 2500.0, 4
    p = PlanWriter(W, H, scale=100)

    p.layer("A-WALL", width_pt=0.7)
    p.wall((0, 0), (W, 0), EXT, openings=[(3000, 2400)])
    p.wall((W, 0), (W, H), EXT)
    p.wall((W, H), (0, H), EXT)
    p.wall((0, H), (0, 0), EXT)
    p.wall((12000, 0), (12000, H), INT, openings=[(8000, 1200)])

    p.layer("A-DOOR", width_pt=0.35)
    p.door_swing((1800, 0), 1200, 90.0)                       # double entrance doors
    p.door_swing((4200, 0), 1200, 90.0, swing_deg=-90.0)
    p.door_swing((12000, 7400), 1200, 0.0)

    # Travelator: a 20 m band, longer than any escalator flight.
    p.layer("A-CONV", width_pt=0.3)
    bx, by = 2000.0, 2000.0
    p.line(bx, by, bx, by + RUN * 0.7)
    p.line(bx + BAND, by, bx + BAND, by + RUN * 0.7)
    pallets = 28
    for i in range(pallets):
        py = by + (RUN * 0.7) * i / (pallets - 1)
        p.line(bx, py, bx + BAND, py)

    p.layer("A-FIRE-EQPM", width_pt=0.4)
    p.polyline([(9000, 600), (9800, 600), (9800, 850), (9000, 850)], close=True)

    p.layer("A-PARK", width_pt=0.3)
    for i in range(BAYS):
        x = 13000.0 + (BAY_W + 100.0) * i
        p.polyline([(x, 2000), (x + BAY_W, 2000), (x + BAY_W, 2000 + BAY_L),
                    (x, 2000 + BAY_L)], close=True)

    p.layer("A-ANNO", width_pt=0.25)
    p.text("SANH", 6000, 12000, 13.0)
    p.text("TRAVELATOR", 3800, 8000, 8.0)
    p.text("BAI DE XE", 16000, 12000, 13.0)

    p.layer("A-DIMS", width_pt=0.25)
    p.dimension((0, 0), (W, 0), -1400)

    path = os.path.join(outdir, "concourse.pdf")
    p.save(path, title="Concourse 1:100")
    return {
        "file": "concourse.pdf",
        "scale": 100,
        "room_count": 2,
        "travelator": {"symbol": "travelator", "run_mm": RUN * 0.7, "width_mm": BAND},
        "fire_equipment": {"symbol": "fire_equipment", "items": 1},
        "parking": {"symbol": "parking_bay", "bays": BAYS},
        "notes": "a 14 m run: too long for escalator, which stands down",
    }


# ---------------------------------------------------------------------------
# Fixture 13: institution -- lab, ward, auditorium, plant room
# ---------------------------------------------------------------------------
def institution(outdir: str) -> dict:
    W, H = 30000.0, 18000.0
    EXT, INT = 300.0, 200.0
    SEAT_COLS, SEAT_ROWS, PITCH = 8, 6, 900.0
    BEDS, BAY_PITCH = 4, 3000.0
    p = PlanWriter(W, H, scale=100)

    p.layer("A-WALL", width_pt=0.7)
    p.wall((0, 0), (W, 0), EXT, openings=[(6000, 1200)])
    p.wall((W, 0), (W, H), EXT)
    p.wall((W, H), (0, H), EXT)
    p.wall((0, H), (0, 0), EXT)
    p.wall((15000, 0), (15000, H), INT, openings=[(4500, 1200), (13500, 1200)])
    p.wall((0, 9000), (W, 9000), INT, openings=[(7000, 1200), (22000, 1200)])

    p.layer("A-DOOR", width_pt=0.35)
    p.door_swing((5400, 0), 1200, 90.0)
    p.door_swing((15000, 3900), 1200, 0.0)
    p.door_swing((15000, 12900), 1200, 0.0)
    p.door_swing((6400, 9000), 1200, 90.0)
    p.door_swing((21400, 9000), 1200, 90.0)

    # Laboratory: two wall benches and an island.
    p.layer("I-BENCH", width_pt=0.3)
    for x, y, w, h in ((500, 500, 5000, 750), (6000, 500, 4000, 750), (3000, 4000, 6000, 1800)):
        p.polyline([(x, y), (x + w, y), (x + w, y + h), (x, y + h)], close=True)

    # Ward: four bed bays at a regular pitch.
    p.layer("I-FURN", width_pt=0.3)
    for i in range(BEDS):
        x = 16000.0 + BAY_PITCH * i
        p.polyline([(x, 600), (x + 1000, 600), (x + 1000, 2700), (x, 2700)], close=True)

    # Auditorium: six rows of eight seats.
    p.layer("I-SEAT", width_pt=0.25)
    for r in range(SEAT_ROWS):
        for c in range(SEAT_COLS):
            x = 4000.0 + 580.0 * c
            y = 10500.0 + PITCH * r
            p.polyline([(x, y), (x + 520, y), (x + 520, y + 550), (x, y + 550)], close=True)

    # Plant room: two air handling units on a mechanical layer.
    p.layer("M-EQPM-AHU", width_pt=0.4)
    for x in (16500.0, 20500.0):
        p.polyline([(x, 10500), (x + 2400, 10500), (x + 2400, 12100), (x, 12100)], close=True)

    p.layer("A-ANNO", width_pt=0.25)
    p.text("PHONG THI NGHIEM", 2000, 7500, 11.0)
    p.text("PHONG BENH", 18000, 7500, 11.0)
    p.text("HOI TRUONG", 2000, 16500, 11.0)
    p.text("PHONG KY THUAT", 17000, 16500, 11.0)
    p.text("AHU-01", 17000, 13000, 7.0)

    p.layer("A-DIMS", width_pt=0.25)
    p.dimension((0, 0), (W, 0), -1600)

    path = os.path.join(outdir, "institution.pdf")
    p.save(path, title="Institution 1:100")
    return {
        "file": "institution.pdf",
        "scale": 100,
        "room_count": 4,
        "lab_bench": {"symbol": "lab_bench", "wall_benches": 2, "islands": 1},
        "ward": {"symbol": "ward_bay", "bays": BEDS, "bay_pitch_mm": BAY_PITCH},
        "seating": {"symbol": "theatre_seating", "seats": SEAT_COLS * SEAT_ROWS,
                    "rows": SEAT_ROWS, "row_pitch_mm": PITCH},
        "plant": {"symbol": "plant_equipment", "items": 2},
        "notes": "the ward also reports its beds as furniture; both are true",
    }


# ---------------------------------------------------------------------------
# Fixture 14: warehouse -- grid and escape route at plan scope, plus fitments
# ---------------------------------------------------------------------------
def _arrow_glyph(cx, cy, length, angle_deg=90.0):
    a = math.radians(angle_deg)
    return [
        (cx + length * math.cos(a), cy + length * math.sin(a)),
        (cx + 0.35 * length * math.cos(a + 2.4), cy + 0.35 * length * math.sin(a + 2.4)),
        (cx + 0.35 * length * math.cos(a - 2.4), cy + 0.35 * length * math.sin(a - 2.4)),
    ]


def _cloud(cx, cy, r, lobes=11, depth=0.2, steps=96):
    return [
        (
            cx + r * (1 + depth * math.cos(lobes * 2 * math.pi * i / steps))
            * math.cos(2 * math.pi * i / steps),
            cy + r * (1 + depth * math.cos(lobes * 2 * math.pi * i / steps))
            * math.sin(2 * math.pi * i / steps),
        )
        for i in range(steps)
    ]


def warehouse(outdir: str) -> dict:
    W, H = 30000.0, 12000.0
    EXT, INT = 300.0, 200.0
    TILE = 600.0
    DOCKS, DOCK_PITCH = 3, 4000.0
    p = PlanWriter(W, H, scale=100, margin_mm=5500)

    # Structural grid first: it belongs to the drawing, not to any room.
    p.layer("S-GRID", width_pt=0.25)
    for i, x in enumerate((5000.0, 15000.0, 25000.0)):
        p.line(x, -1500.0, x, H + 500.0)
        p.arc(x, -1500.0, 450.0, 0.0, 2 * math.pi)
        p.text(chr(ord("A") + i), x - 130, -1650.0, 7.0)
    for j, y in enumerate((3000.0, 9000.0)):
        p.line(-1500.0, y, W + 500.0, y)
        p.arc(-1500.0, y, 450.0, 0.0, 2 * math.pi)
        p.text(str(j + 1), -1630.0, y - 150.0, 7.0)

    p.layer("A-WALL", width_pt=0.7)
    p.wall((0, 0), (W, 0), EXT, openings=[(2000, 1200)])
    p.wall((W, 0), (W, H), EXT)
    p.wall((W, H), (0, H), EXT)
    p.wall((0, H), (0, 0), EXT)
    p.wall((10000, 0), (10000, H), INT, openings=[(6000, 1200)])
    p.wall((20000, 0), (20000, H), INT, openings=[(6000, 1200)])

    p.layer("A-DOOR", width_pt=0.35)
    p.door_swing((1400, 0), 1200, 90.0)
    p.door_swing((10000, 5400), 1200, 0.0)
    p.door_swing((20000, 5400), 1200, 0.0)

    # Kitchen: a run of units, the canopy over it, and floor gullies.
    p.layer("A-FURN", width_pt=0.3)
    x = 600.0
    for length in (2400.0, 600.0, 600.0):
        p.polyline([(x, 600), (x + length, 600), (x + length, 1200), (x, 1200)], close=True)
        x += length
    p.layer("M-EXTR-KEF", width_pt=0.3)
    p.polyline([(600, 400), (3600, 400), (3600, 1800), (600, 1800)], close=True)
    p.layer("P-DRAI-FLOR", width_pt=0.3)
    for gx in (5000.0, 8000.0):
        p.polyline([(gx, 3000), (gx + 200, 3000), (gx + 200, 3200), (gx, 3200)], close=True)

    # Office: a raised access floor on a 600 tile grid.
    p.layer("A-FLOR-RAIS", width_pt=0.15)
    tx = 10000.0 + TILE
    while tx < 20000.0:
        p.line(tx, 300, tx, H - 300)
        tx += TILE
    ty = TILE
    while ty < H:
        p.line(10300, ty, 19700, ty)
        ty += TILE

    # Loading bay: matching leveller plates in a row.
    p.layer("A-DOCK", width_pt=0.35)
    for i in range(DOCKS):
        dx = 21000.0 + DOCK_PITCH * i
        p.polyline([(dx, 600), (dx + 2400, 600), (dx + 2400, 2600), (dx, 2600)], close=True)

    # Escape route: crosses every room, so only the plan scope can see it.
    p.layer("A-FIRE-ESCP", width_pt=0.3)
    p.polyline([(2000, 2000), (2000, 10500), (28000, 10500), (28000, 11500)])

    p.layer("A-ANNO", width_pt=0.25)
    p.text("BEP", 4000, 6000, 11.0)
    p.text("FALL 1:80", 5000, 4000, 7.0)
    p.text("VAN PHONG", 13000, 6000, 11.0)
    p.text("BOC XEP", 23000, 6000, 11.0)
    p.text("TRAVEL DISTANCE 36m", 12000, 10800, 8.0)

    # Drawing furniture: none of it belongs to a room.
    p.layer("A-NORT", width_pt=0.3)
    p.polyline(_arrow_glyph(33000.0, 8000.0, 2200.0), close=True)
    p.text("N", 32850.0, 10600.0, 9.0)

    p.layer("A-SCLB", width_pt=0.3)
    for i in range(5):
        bx = 2000.0 + 2000.0 * i
        p.polyline([(bx, -4200), (bx + 2000, -4200), (bx + 2000, -3900), (bx, -3900)], close=True)
    p.text("0", 1900.0, -4800.0, 7.0)
    p.text("10", 11800.0, -4800.0, 7.0)

    p.layer("A-SECT", width_pt=0.3)
    for sy in (-1200.0, 13200.0):
        p.arc(7000.0, sy, 450.0, 0.0, 2 * math.pi)
        p.text("S", 6870.0, sy - 150.0, 7.0)
    p.line(7000.0, -1200.0, 7000.0, 13200.0)

    p.layer("A-REVC", width_pt=0.3)
    p.polyline(_cloud(24000.0, 4000.0, 2200.0), close=True)
    p.text("REV 2", 26600.0, 6400.0, 7.0)

    p.layer("A-ANNO", width_pt=0.25)
    p.text("FFL +0.000", 4000.0, 5000.0, 7.0)
    p.text("FFL +0.150", 23000.0, 5000.0, 7.0)

    p.layer("A-DIMS", width_pt=0.25)
    p.dimension((0, 0), (W, 0), -2000)

    path = os.path.join(outdir, "warehouse.pdf")
    p.save(path, title="Warehouse 1:100")
    return {
        "file": "warehouse.pdf",
        "scale": 100,
        "room_count": 3,
        "grid": {"symbol": "structural_grid", "references": ["1", "2", "A", "B", "C"]},
        "escape_route": {"symbol": "escape_route", "stated_m": 36.0},
        "drainage": {"symbol": "drainage", "gullies": 2, "fall": "1:80"},
        "extract_canopy": {"symbol": "extract_canopy", "canopy_mm": [3000.0, 1400.0]},
        "loading_dock": {"symbol": "loading_dock", "docks": DOCKS},
        "raised_floor": {"symbol": "raised_floor", "tile_mm": TILE},
        "north_arrow": {"symbol": "north_arrow", "bearing_deg": 0.0},
        "scale_bar": {"symbol": "scale_bar", "divisions": 5, "stated_m": 10.0},
        "section_mark": {"symbol": "section_mark", "label": "S-S"},
        "revision_cloud": {"symbol": "revision_cloud", "tag": "REV 2"},
        "level_spot": {"symbol": "level_spot", "levels_m": [0.0, 0.15]},
        "notes": "grid and escape route belong to the drawing, not to any one room",
    }


# ---------------------------------------------------------------------------
# Fixture 15: a titled sheet -- dimension chain, elevations, schedule, legend
# ---------------------------------------------------------------------------
def titled_sheet(outdir: str) -> dict:
    W, H = 18000.0, 10000.0
    EXT, INT = 300.0, 200.0
    BAYS = (6000.0, 6000.0, 6000.0)
    DOORS = ("D01", "D02", "D03", "D04")
    MATERIALS = ("BRICKWORK", "BLOCKWORK", "INSULATION")
    p = PlanWriter(W, H, scale=100, margin_mm=6000)

    p.layer("A-WALL", width_pt=0.7)
    p.wall((0, 0), (W, 0), EXT, openings=[(3000, 1200)])
    p.wall((W, 0), (W, H), EXT)
    p.wall((W, H), (0, H), EXT, openings=[(2400, 1200)])
    p.wall((0, H), (0, 0), EXT)
    p.wall((6000, 0), (6000, H), INT, openings=[(5000, 1200)])
    p.wall((12000, 0), (12000, H), INT, openings=[(5000, 1200)])

    p.layer("A-DOOR", width_pt=0.35)
    p.door_swing((2400, 0), 1200, 90.0)
    p.door_swing((6000, 4400), 1200, 0.0)
    p.door_swing((12000, 4400), 1200, 0.0)
    p.door_swing((16200, H), 1200, -90.0)

    # A setting-out chain: three bays that should sum to the overall width.
    p.layer("A-DIMS", width_pt=0.25)
    x = 0.0
    for bay in BAYS:
        p.dimension((x, 0), (x + bay, 0), -1500)
        x += bay

    # Elevation marks: lone bubbles with arrows, attached to nothing.
    p.layer("A-ELEV", width_pt=0.3)
    for label, (bx, by), angle in (
        ("1", (-2600.0, 5000.0), 0.0),
        ("2", (20600.0, 5000.0), 180.0),
    ):
        p.arc(bx, by, 450.0, 0.0, 2 * math.pi)
        p.text(label, bx - 120.0, by - 160.0, 8.0)
        tip = (bx + 900.0 * math.cos(math.radians(angle)),
               by + 900.0 * math.sin(math.radians(angle)))
        base = 0.4 * 900.0
        p.polyline(
            [
                tip,
                (bx + base * math.cos(math.radians(angle) + 2.4),
                 by + base * math.sin(math.radians(angle) + 2.4)),
                (bx + base * math.cos(math.radians(angle) - 2.4),
                 by + base * math.sin(math.radians(angle) - 2.4)),
            ],
            close=True,
        )

    p.layer("A-ANNO", width_pt=0.25)
    p.text("DOOR SCHEDULE", 21000.0, 9000.0, 9.0)
    for i, ref in enumerate(DOORS):
        p.text(ref, 21000.0, 8000.0 - 900.0 * i, 7.0)

    p.text("LEGEND", 21000.0, 4200.0, 9.0)
    p.layer("A-LEGD", width_pt=0.3)
    for i, name in enumerate(MATERIALS):
        sy = 3000.0 - 1200.0 * i
        p.polyline([(21000, sy), (21600, sy), (21600, sy + 600), (21000, sy + 600)], close=True)
        p.text(name, 22000.0, sy + 200.0, 7.0)

    p.layer("A-ANNO", width_pt=0.25)
    p.text("PHONG A", 2500, 5000, 10.0)
    p.text("PHONG B", 8500, 5000, 10.0)
    p.text("PHONG C", 14500, 5000, 10.0)

    path = os.path.join(outdir, "titled_sheet.pdf")
    p.save(path, title="Titled sheet 1:100")
    return {
        "file": "titled_sheet.pdf",
        "scale": 100,
        "room_count": 3,
        "doors": len(DOORS),
        "dimension_chain": {"symbol": "dimension_chain", "links": len(BAYS),
                            "stated_mm": sum(BAYS)},
        "elevation_mark": {"symbol": "elevation_mark", "count": 2},
        "door_schedule": {"symbol": "door_schedule", "listed": len(DOORS)},
        "hatch_legend": {"symbol": "hatch_legend", "entries": list(MATERIALS)},
        "notes": "the schedule lists exactly the doors the plan draws",
    }


# ---------------------------------------------------------------------------
# Fixture 16: hatched plan -- patterns named from the drawing's own legend
# ---------------------------------------------------------------------------
def _rulings(box, angle_deg, spacing):
    """Parallel rulings clipped to a box, as a CAD hatch expands to."""
    x0, y0, x1, y1 = box
    a = math.radians(angle_deg)
    dx, dy = math.cos(a), math.sin(a)
    nx, ny = -dy, dx
    corners = ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
    offs = [px * nx + py * ny for px, py in corners]
    out = []
    off = min(offs) + spacing
    while off < max(offs):
        bx, by = nx * off, ny * off
        lo, hi = -1e12, 1e12
        ok = True
        for origin, delta, low, high in ((bx, dx, x0, x1), (by, dy, y0, y1)):
            if abs(delta) < 1e-12:
                if not (low <= origin <= high):
                    ok = False
                break
            ta, tb = (low - origin) / delta, (high - origin) / delta
            lo, hi = max(lo, min(ta, tb)), min(hi, max(ta, tb))
        if ok and hi - lo > 1.0:
            out.append(((bx + dx * lo, by + dy * lo), (bx + dx * hi, by + dy * hi)))
        off += spacing
    return out


def hatched_plan(outdir: str) -> dict:
    W, H = 9000.0, 6000.0
    EXT, INT = 300.0, 200.0
    SPACING = 120.0
    BAR_DIVISION, BAR_DIVISIONS = 2000.0, 5
    NORTH_DEG = 90.0
    p = PlanWriter(W, H, scale=50, margin_mm=6000)

    p.layer("A-WALL", width_pt=0.7)
    p.wall((0, 0), (W, 0), EXT, openings=[(1500, 1000)])
    p.wall((W, 0), (W, H), EXT)
    p.wall((W, H), (0, H), EXT)
    p.wall((0, H), (0, 0), EXT)
    p.wall((5000, 0), (5000, H), INT, openings=[(3000, 900)])

    p.layer("A-DOOR", width_pt=0.35)
    p.door_swing((1000, 0), 1000, 90.0)
    p.door_swing((5000, 2550), 900, 0.0)

    # The external wall is hatched one way, the partition another.
    p.layer("A-HATCH", width_pt=0.15)
    for a, b in _rulings((0.0, -EXT / 2, W, EXT / 2), 45.0, SPACING):
        p.line(a[0], a[1], b[0], b[1])
    for a, b in _rulings((5000.0 - INT / 2, 500.0, 5000.0 + INT / 2, H - 500.0), 45.0, SPACING):
        p.line(a[0], a[1], b[0], b[1])
    for a, b in _rulings((5000.0 - INT / 2, 500.0, 5000.0 + INT / 2, H - 500.0), 135.0, SPACING):
        p.line(a[0], a[1], b[0], b[1])

    # The legend: the same two patterns, captioned.
    p.layer("A-LEGD", width_pt=0.3)
    lx = 11000.0
    for i, (name, angles) in enumerate((("GACH XAY", (45.0,)), ("BE TONG", (45.0, 135.0)))):
        ly = 3000.0 - 1400.0 * i
        p.polyline([(lx, ly), (lx + 700, ly), (lx + 700, ly + 700), (lx, ly + 700)], close=True)
        p.layer("A-HATCH", width_pt=0.15)
        for angle in angles:
            for a, b in _rulings((lx, ly, lx + 700, ly + 700), angle, SPACING):
                p.line(a[0], a[1], b[0], b[1])
        p.layer("A-LEGD", width_pt=0.3)
        p.text(name, lx + 1100.0, ly + 250.0, 8.0)

    p.layer("A-ANNO", width_pt=0.25)
    p.text("CHU THICH", lx, 4600.0, 9.0)
    p.text("PHONG KHACH", 1600, 3000, 10.0)
    p.text("30.0 m2", 2000, 2300, 7.0)
    p.text("BEP", 6900, 3000, 10.0)
    p.text("24.0 m2", 6600, 2300, 7.0)

    p.layer("A-DIMS", width_pt=0.25)
    p.dimension((0, 0), (W, 0), -1200)

    # A scale bar: an independent witness to the scale read off the dimension.
    p.layer("A-SCLB", width_pt=0.3)
    for i in range(BAR_DIVISIONS):
        bx = BAR_DIVISION * i
        p.polyline(
            [(bx, -3100), (bx + BAR_DIVISION, -3100),
             (bx + BAR_DIVISION, -2800), (bx, -2800)],
            close=True,
        )
    p.text("0", -100.0, -3700.0, 7.0)
    p.text(str(int(BAR_DIVISION * BAR_DIVISIONS / 1000)), BAR_DIVISION * BAR_DIVISIONS - 200.0,
           -3700.0, 7.0)

    # A north arrow: the only orientation the drawing records.
    p.layer("A-NORT", width_pt=0.3)
    nx, ny, nl = 13800.0, 1200.0, 1400.0
    a = math.radians(NORTH_DEG)
    p.polyline(
        [
            (nx + nl * math.cos(a), ny + nl * math.sin(a)),
            (nx + 0.35 * nl * math.cos(a + 2.4), ny + 0.35 * nl * math.sin(a + 2.4)),
            (nx + 0.35 * nl * math.cos(a - 2.4), ny + 0.35 * nl * math.sin(a - 2.4)),
        ],
        close=True,
    )
    p.text("N", nx + nl * math.cos(a) - 130.0, ny + nl * math.sin(a) + 300.0, 9.0)

    path = os.path.join(outdir, "hatched_plan.pdf")
    p.save(path, title="Hatched plan 1:50")
    return {
        "file": "hatched_plan.pdf",
        "scale": 50,
        "room_count": 2,
        "hatch": {
            "symbol": "hatch_pattern",
            "materials": ["BE TONG", "GACH XAY"],
            "styles": ["cross", "single"],
        },
        "scale_bar": {
            "symbol": "scale_bar",
            "divisions": BAR_DIVISIONS,
            "stated_m": BAR_DIVISION * BAR_DIVISIONS / 1000.0,
        },
        "north_arrow": {"symbol": "north_arrow", "bearing_deg": (90.0 - NORTH_DEG) % 360.0},
        "notes": "materials are named from the drawing's legend, not a built-in table",
    }


def main() -> int:
    outdir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "plans")
    os.makedirs(outdir, exist_ok=True)
    truth = [
        apartment(outdir),
        studio(outdir),
        bay_house(outdir),
        corner_house(outdir),
        folding_door(outdir),
        revolving_lobby(outdir),
        commercial_unit(outdir),
        services(outdir),
        fitted_flat(outdir),
        transport_hall(outdir),
        dwelling(outdir),
        concourse(outdir),
        institution(outdir),
        warehouse(outdir),
        titled_sheet(outdir),
        hatched_plan(outdir),
    ]
    with open(os.path.join(outdir, "ground_truth.json"), "w") as fh:
        json.dump(truth, fh, indent=2)
    for t in truth:
        print(f"wrote {os.path.join(outdir, t['file'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
