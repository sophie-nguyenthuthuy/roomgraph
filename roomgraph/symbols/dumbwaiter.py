"""Dumbwaiter: a lift car too small to stand in.

The same crossed box as `lift`, at a size that rules a person out. The two
ranges are kept apart deliberately -- below 880 mm nothing carries passengers,
above 900 mm nothing is a service hoist -- so the pair can never both claim one
box.
"""

from __future__ import annotations

from ..geom import oriented_extent, polygon_area
from . import Fixture, Match, RoomContext, Symbol, crossed_diagonals, ring_corners

CAR_LONG = (350.0, 880.0)
CAR_SHORT = (300.0, 880.0)
MAX_ASPECT = 1.8
CORNER_TOL = 0.22


def detect(ctx: RoomContext) -> Match | None:
    diagonals = ctx.straight_strokes(min_length=200.0)
    if len(diagonals) < 2:
        return None

    for loop in ctx.loops():
        corners = ring_corners(loop)
        if len(corners) != 4:
            continue
        long_side, short_side = oriented_extent(corners)
        if short_side <= 0 or long_side / short_side > MAX_ASPECT:
            continue
        if not (CAR_LONG[0] <= long_side <= CAR_LONG[1]):
            continue
        if not (CAR_SHORT[0] <= short_side <= CAR_SHORT[1]):
            continue

        tol = CORNER_TOL * min(long_side, short_side)
        if crossed_diagonals(corners, diagonals, tol) < 2:
            continue
        return Match(
            kind="dumbwaiter",
            confidence=0.84,
            meta={
                "car_mm": [round(long_side, 1), round(short_side, 1)],
                "car_area_m2": round(abs(polygon_area(corners)) / 1e6, 3),
            },
        )
    return None


SYMBOL = Symbol(
    id="dumbwaiter",
    name="Dumbwaiter",
    kind="dumbwaiter",
    detect=detect,
    scope="room",
    priority=15,
    description="A crossed box too small to be a passenger car.",
)


_ROOM = [(0, 0), (3000, 0), (3000, 3000), (0, 3000)]


def _crossed(x, y, w, h):
    return [
        [(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)],
        [(x, y), (x + w, y + h)],
        [(x + w, y), (x, y + h)],
    ]


FIXTURES = [
    Fixture(
        name="a 600 by 600 service hoist",
        polygon=_ROOM,
        strokes=_crossed(500, 500, 600, 600),
        expect=True,
    ),
    Fixture(
        name="an 800 by 500 hoist",
        polygon=_ROOM,
        strokes=_crossed(500, 500, 800, 500),
        expect=True,
    ),
    Fixture(
        name="a 1600 mm car is a passenger lift",
        polygon=_ROOM,
        strokes=_crossed(300, 300, 1600, 1400),
        expect=False,
    ),
    Fixture(
        name="a plain 600 mm box with no diagonals",
        polygon=_ROOM,
        strokes=[[(500, 500), (1100, 500), (1100, 1100), (500, 1100), (500, 500)]],
        expect=False,
    ),
    Fixture(
        name="an empty room",
        polygon=_ROOM,
        strokes=[],
        expect=False,
    ),
]
