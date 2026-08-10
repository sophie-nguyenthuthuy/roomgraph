"""North arrow: the plan's orientation, which nothing else records.

Worth having for one output only -- the bearing. A floor plan carries no
compass information anywhere else, so without this the model cannot say which
way the building faces, and every daylight, overheating or feng shui question
downstream is unanswerable.

The mark is a glyph beside an "N". The glyph's long axis, measured from its
centroid to its furthest vertex, is the direction it points; the bearing is
reported clockwise from the top of the sheet.
"""

from __future__ import annotations

import math
import re

from ..geom import Pt, dist, polygon_centroid
from . import Fixture, Match, PlanContext, Symbol, fold_text

LABEL = r"^(n|north|bac|huong\s*bac)$"
GLYPH_SIZE = (300.0, 6000.0)
LABEL_REACH = 3.0        # of the glyph's own size
MIN_POINTS = 3


def _glyphs(ctx: PlanContext) -> list[tuple[Pt, list[Pt], float]]:
    out: list[tuple[Pt, list[Pt], float]] = []
    for pts in ctx.strokes:
        if len(pts) < MIN_POINTS:
            continue
        size = max(dist(a, b) for a in pts for b in pts)
        if not (GLYPH_SIZE[0] <= size <= GLYPH_SIZE[1]):
            continue
        out.append((polygon_centroid(pts), list(pts), size))
    return out


def detect(ctx: PlanContext) -> Match | None:
    labels = [t for t in ctx.texts if re.fullmatch(LABEL, fold_text(t.text).strip())]
    if not labels:
        return None

    best: Match | None = None
    for centroid, pts, size in _glyphs(ctx):
        near = [t for t in labels if dist(t.at, centroid) <= LABEL_REACH * size]
        if not near:
            continue
        apex = max(pts, key=lambda p: dist(p, centroid))
        direction = apex - centroid
        if direction.norm() < 1e-6:
            continue
        # Bearing clockwise from the top of the sheet, which is how a drawing
        # is read regardless of which way its axes run.
        bearing = (90.0 - math.degrees(math.atan2(direction.y, direction.x))) % 360.0
        conf = 0.78 + 0.08 * min(1.0, (LABEL_REACH * size - dist(near[0].at, centroid))
                                 / (LABEL_REACH * size))
        match = Match(
            kind="north_arrow",
            confidence=min(0.92, conf),
            meta={
                "bearing_deg": round(bearing, 1),
                "glyph_mm": round(size, 1),
                "label": near[0].text.strip(),
            },
        )
        if best is None or match.confidence > best.confidence:
            best = match
    return best


SYMBOL = Symbol(
    id="north_arrow",
    name="North arrow",
    kind="north_arrow",
    detect=detect,
    scope="plan",
    priority=10,
    description="An arrow glyph beside an N, reported as a bearing from sheet-up.",
)


def _arrow(cx, cy, length=2000.0, angle_deg=90.0):
    a = math.radians(angle_deg)
    tip = (cx + length * math.cos(a), cy + length * math.sin(a))
    left = (cx + 0.35 * length * math.cos(a + 2.4), cy + 0.35 * length * math.sin(a + 2.4))
    right = (cx + 0.35 * length * math.cos(a - 2.4), cy + 0.35 * length * math.sin(a - 2.4))
    return [tip, left, right, tip]


FIXTURES = [
    Fixture(
        name="an arrow pointing up the sheet",
        scope="plan",
        strokes=[_arrow(0.0, 0.0)],
        placed_texts=[("N", (0.0, 2600.0))],
        expect=True,
    ),
    Fixture(
        name="a plan rotated so north runs to the right",
        scope="plan",
        strokes=[_arrow(0.0, 0.0, angle_deg=0.0)],
        placed_texts=[("N", (2600.0, 0.0))],
        expect=True,
    ),
    Fixture(
        name="the Vietnamese label",
        scope="plan",
        strokes=[_arrow(0.0, 0.0)],
        placed_texts=[("BẮC", (0.0, 2600.0))],
        expect=True,
    ),
    Fixture(
        name="an arrow glyph with no N beside it",
        scope="plan",
        strokes=[_arrow(0.0, 0.0)],
        expect=False,
    ),
    Fixture(
        name="an N label with no glyph",
        scope="plan",
        strokes=[],
        placed_texts=[("N", (0.0, 0.0))],
        expect=False,
    ),
    Fixture(
        name="an empty drawing",
        scope="plan",
        strokes=[],
        expect=False,
    ),
]
