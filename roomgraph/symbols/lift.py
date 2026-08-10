"""Lift car: a rectangle with both diagonals drawn across it.

The crossed box is the standard plan mark for a lift, and the crossing is what
carries it -- a bare rectangle of that size is a cupboard, a table or a shaft
with nothing in it. Both diagonals must be present and must actually reach
opposite corners.
"""

from __future__ import annotations

from ..geom import oriented_extent, polygon_area
from . import Fixture, Match, RoomContext, Symbol, crossed_diagonals, ring_corners

CAR_LONG = (900.0, 3000.0)
CAR_SHORT = (800.0, 2600.0)
CORNER_TOL = 0.18        # how near a diagonal end must land, as a fraction of the car
MIN_DIAGONAL = 0.7       # against the true corner-to-corner distance


def detect(ctx: RoomContext) -> Match | None:
    diagonals = ctx.straight_strokes(min_length=500.0)
    if len(diagonals) < 2:
        return None

    for loop in ctx.loops():
        corners = ring_corners(loop)
        if len(corners) != 4:
            continue
        if abs(polygon_area(corners)) / 1e6 < 0.7:
            continue
        long_side, short_side = oriented_extent(corners)
        if not (CAR_LONG[0] <= long_side <= CAR_LONG[1]):
            continue
        if not (CAR_SHORT[0] <= short_side <= CAR_SHORT[1]):
            continue

        tol = CORNER_TOL * min(long_side, short_side)
        crossed = crossed_diagonals(corners, diagonals, tol)
        if crossed < 2:
            continue

        conf = 0.82 + 0.08 * min(1.0, (3000.0 - abs(long_side - 1600.0)) / 3000.0)
        return Match(
            kind="lift",
            confidence=min(0.94, conf),
            meta={
                "car_mm": [round(long_side, 1), round(short_side, 1)],
                "diagonals": crossed,
                "car_area_m2": round(abs(polygon_area(corners)) / 1e6, 2),
            },
        )
    return None


SYMBOL = Symbol(
    id="lift",
    name="Lift car",
    kind="lift",
    detect=detect,
    scope="room",
    priority=10,
    description="A car-sized rectangle with both diagonals drawn corner to corner.",
)


_SHAFT = [(0, 0), (2200, 0), (2200, 2000), (0, 2000)]


def _crossed_box(x, y, w, h):
    box = [(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)]
    return [
        box,
        [(x, y), (x + w, y + h)],
        [(x + w, y), (x, y + h)],
    ]


FIXTURES = [
    Fixture(
        name="1600 by 1400 car with both diagonals",
        polygon=_SHAFT,
        strokes=_crossed_box(300, 300, 1600, 1400),
        expect=True,
    ),
    Fixture(
        name="a small 1100 by 1400 platform lift",
        polygon=_SHAFT,
        strokes=_crossed_box(300, 300, 1100, 1400),
        expect=True,
    ),
    Fixture(
        name="a plain rectangle with no diagonals is a cupboard",
        polygon=_SHAFT,
        strokes=[[(300, 300), (1900, 300), (1900, 1700), (300, 1700), (300, 300)]],
        expect=False,
    ),
    Fixture(
        name="only one diagonal drawn",
        polygon=_SHAFT,
        strokes=[
            [(300, 300), (1900, 300), (1900, 1700), (300, 1700), (300, 300)],
            [(300, 300), (1900, 1700)],
        ],
        expect=False,
    ),
    Fixture(
        name="diagonals that do not reach the corners",
        polygon=_SHAFT,
        strokes=[
            [(300, 300), (1900, 300), (1900, 1700), (300, 1700), (300, 300)],
            [(700, 700), (1500, 1300)],
            [(1500, 700), (700, 1300)],
        ],
        expect=False,
    ),
    Fixture(
        name="a crossed box far too small to be a car",
        polygon=_SHAFT,
        strokes=_crossed_box(300, 300, 600, 500),
        expect=False,
    ),
    Fixture(
        name="an empty shaft",
        polygon=_SHAFT,
        strokes=[],
        expect=False,
    ),
]
