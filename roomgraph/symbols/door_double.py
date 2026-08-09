"""Double (French) door: a mirrored pair of swing arcs meeting in the middle.

Each leaf is half the opening, so the arcs are half-width and hinge on opposite
jambs. That half-width radius is exactly what disqualifies the single-leaf
detector, which keeps the two symbols from fighting over the same opening.
"""

from __future__ import annotations

import math

from ..geom import dist
from . import Fixture, Match, OpeningContext, Symbol, arc_points

RADIUS_RATIO = (0.35, 0.68)   # each leaf spans about half the opening
MIN_SWING_DEG = 45.0
MAX_SWING_DEG = 200.0
HINGE_TOLERANCE = 0.25        # fraction of opening width


def detect(ctx: OpeningContext) -> Match | None:
    if ctx.width <= 0:
        return None
    left, right = ctx.jambs
    on_left: list[float] = []
    on_right: list[float] = []

    for arc in ctx.arcs(min_span_deg=MIN_SWING_DEG):
        if math.degrees(arc.span) > MAX_SWING_DEG:
            continue
        ratio = arc.radius / ctx.width
        if not (RADIUS_RATIO[0] <= ratio <= RADIUS_RATIO[1]):
            continue
        dl, dr = dist(arc.centre, left), dist(arc.centre, right)
        limit = HINGE_TOLERANCE * ctx.width
        if dl <= limit and dl <= dr:
            on_left.append(arc.radius)
        elif dr <= limit:
            on_right.append(arc.radius)

    if not (on_left and on_right):
        return None

    rl, rr = max(on_left), max(on_right)
    # Matched leaves that together fill the opening are the giveaway.
    symmetry = abs(rl - rr) / max(rl, rr)
    fill = (rl + rr) / ctx.width
    if symmetry > 0.25 or not (0.75 <= fill <= 1.35):
        return None

    conf = 0.72 + 0.15 * (1.0 - symmetry / 0.25) + 0.10 * max(0.0, 1.0 - abs(fill - 1.0) / 0.35)
    return Match(
        kind="door",
        confidence=min(0.97, conf),
        meta={
            "leaf_width_mm": round((rl + rr) / 2.0, 1),
            "panels": 2,
            "symmetry": round(symmetry, 3),
        },
    )


SYMBOL = Symbol(
    id="door_double",
    name="Double door, two leaves",
    kind="door",
    detect=detect,
    scope="opening",
    priority=20,
    description="Two half-width swing arcs hinged on opposite jambs.",
)


FIXTURES = [
    Fixture(
        name="1600 mm French door, two 800 mm leaves",
        width=1600,
        strokes=[
            arc_points((-800, 0), 800, 90, 0),
            arc_points((800, 0), 800, 90, 180),
            [(-800, 0), (-800, 800)],
            [(800, 0), (800, 800)],
        ],
        expect=True,
    ),
    Fixture(
        name="1200 mm double door, arcs only",
        width=1200,
        strokes=[
            arc_points((-600, 0), 600, 90, 0),
            arc_points((600, 0), 600, 90, 180),
        ],
        expect=True,
    ),
    Fixture(
        name="single leaf is not a double door",
        width=900,
        strokes=[
            [(-450, 0), (-450, 900)],
            arc_points((-450, 0), 900, 90, 0),
        ],
        expect=False,
    ),
    Fixture(
        name="two arcs hinged on the same jamb are not a pair",
        width=1600,
        strokes=[
            arc_points((-800, 0), 800, 90, 0),
            arc_points((-800, 0), 700, 90, 0),
        ],
        expect=False,
    ),
    Fixture(name="empty opening", width=1600, strokes=[], expect=False),
]
