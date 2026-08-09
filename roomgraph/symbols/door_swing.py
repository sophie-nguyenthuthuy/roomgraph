"""Single-leaf hinged door: one leaf line plus a swing arc.

The most common symbol in residential plans, and the easiest to identify: the
swing arc is a circle whose centre is the hinge and whose radius is the leaf
width, so radius and opening width agree to within a few percent.
"""

from __future__ import annotations

import math

from ..geom import dist
from . import Fixture, Match, OpeningContext, Symbol, arc_points

MIN_SWING_DEG = 45.0
MAX_SWING_DEG = 200.0
RADIUS_RATIO = (0.70, 1.35)   # arc radius as a fraction of opening width
HINGE_TOLERANCE = 0.40        # how far the hinge may sit from a jamb


def detect(ctx: OpeningContext) -> Match | None:
    if ctx.width <= 0:
        return None
    best: Match | None = None

    for arc in ctx.arcs(min_span_deg=MIN_SWING_DEG):
        span_deg = math.degrees(arc.span)
        if span_deg > MAX_SWING_DEG:
            continue
        ratio = arc.radius / ctx.width
        if not (RADIUS_RATIO[0] <= ratio <= RADIUS_RATIO[1]):
            continue

        hinge_dist = min(dist(arc.centre, j) for j in ctx.jambs)
        if hinge_dist > HINGE_TOLERANCE * ctx.width:
            continue

        # Closer to a true quarter-circle of exactly the leaf width is better.
        conf = 0.60
        conf += 0.20 * max(0.0, 1.0 - abs(ratio - 1.0) / 0.35)
        conf += 0.10 * max(0.0, 1.0 - hinge_dist / (HINGE_TOLERANCE * ctx.width))
        conf += 0.05 * max(0.0, 1.0 - abs(span_deg - 90.0) / 90.0)

        # A leaf line running from the hinge confirms it beyond doubt.
        leaf = None
        for s in ctx.straight_strokes(min_length=0.5 * ctx.width):
            near = min(dist(s.a, arc.centre), dist(s.b, arc.centre))
            if near <= 0.15 * ctx.width and abs(s.length() - arc.radius) <= 0.2 * arc.radius:
                leaf = s
                break
        if leaf is not None:
            conf += 0.05

        conf = min(0.98, conf)
        if best is None or conf > best.confidence:
            best = Match(
                kind="door",
                confidence=conf,
                meta={
                    "leaf_width_mm": round(arc.radius, 1),
                    "swing_deg": round(span_deg, 1),
                    "hinge_offset_mm": round(hinge_dist, 1),
                    "leaf_line": leaf is not None,
                    "panels": 1,
                },
            )
    return best


SYMBOL = Symbol(
    id="door_swing",
    name="Hinged door, single leaf",
    kind="door",
    detect=detect,
    scope="opening",
    priority=10,
    description="Leaf line plus a swing arc whose radius equals the opening width.",
)


FIXTURES = [
    Fixture(
        name="90 degree swing, hinge at the left jamb",
        width=900,
        strokes=[
            [(-450, 0), (-450, 900)],
            arc_points((-450, 0), 900, 90, 0),
        ],
        expect=True,
    ),
    Fixture(
        name="90 degree swing, hinge at the right jamb, opens the other way",
        width=800,
        strokes=[
            [(400, 0), (400, -800)],
            arc_points((400, 0), 800, -90, -180),
        ],
        expect=True,
    ),
    Fixture(
        name="arc only, no leaf line (still a door)",
        width=900,
        strokes=[arc_points((-450, 0), 900, 90, 0)],
        expect=True,
    ),
    Fixture(
        name="60 degree part-open swing",
        width=900,
        strokes=[
            [(-450, 0), (0.0, 779.4)],
            arc_points((-450, 0), 900, 60, 0),
        ],
        expect=True,
    ),
    Fixture(name="empty opening", width=900, strokes=[], expect=False),
    Fixture(
        name="window glazing lines are not a door",
        width=1500,
        strokes=[
            [(-750, 55), (750, 55)],
            [(-750, 0), (750, 0)],
            [(-750, -55), (750, -55)],
        ],
        expect=False,
    ),
    Fixture(
        name="double door arcs are half-width, not this symbol",
        width=1600,
        strokes=[
            arc_points((-800, 0), 800, 90, 0),
            arc_points((800, 0), 800, 90, 180),
        ],
        expect=False,
    ),
    Fixture(
        name="furniture circle is a full loop, not a swing",
        width=900,
        strokes=[arc_points((0, 600), 400, 0, 360)],
        expect=False,
    ),
]
