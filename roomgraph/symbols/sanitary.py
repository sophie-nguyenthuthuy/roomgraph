"""Sanitary fittings: baths, showers, WCs, basins and bidets.

A room-scope symbol, and a catalogue rather than a shape rule. Sanitaryware
comes in a small set of standard sizes, so each closed outline in the room is
measured along its own axes and looked up.

Measuring along the outline's own axes matters: fittings are routinely drawn at
an angle, and an axis-aligned box turns a 1700 mm bath into something square.
"""

from __future__ import annotations

import math

from ..geom import oriented_extent, polygon_area
from . import Fixture, Match, RoomContext, Symbol

# (name, long side range, short side range) in millimetres. Ordered from most
# to least specific, because the ranges overlap and the first match wins.
CATALOGUE: list[tuple[str, tuple[float, float], tuple[float, float]]] = [
    ("bath", (1450.0, 1950.0), (650.0, 900.0)),
    ("shower", (700.0, 1300.0), (700.0, 1300.0)),
    ("wc", (580.0, 820.0), (320.0, 460.0)),
    ("bidet", (480.0, 660.0), (300.0, 440.0)),
    ("basin", (380.0, 780.0), (280.0, 620.0)),
]

MAX_ROOM_AREA_M2 = 30.0   # sanitaryware in a bigger space is probably furniture
MIN_FITTING_AREA = 0.06   # m2, below this it is a drafting mark


def _identify(long_side: float, short_side: float) -> str | None:
    for name, longs, shorts in CATALOGUE:
        if longs[0] <= long_side <= longs[1] and shorts[0] <= short_side <= shorts[1]:
            return name
    return None


def detect(ctx: RoomContext) -> Match | None:
    if ctx.area_m2 > MAX_ROOM_AREA_M2:
        return None

    found: dict[str, int] = {}
    for loop in ctx.loops():
        if abs(polygon_area(loop)) / 1e6 < MIN_FITTING_AREA:
            continue
        long_side, short_side = oriented_extent(loop)
        name = _identify(long_side, short_side)
        if name:
            found[name] = found.get(name, 0) + 1
    if not found:
        return None

    total = sum(found.values())
    conf = 0.55 + 0.12 * min(2, total - 1)
    if "wc" in found or "bath" in found:
        conf += 0.08  # the two least ambiguous fittings
    return Match(
        kind="sanitary",
        confidence=min(0.92, conf),
        meta={
            "fittings": dict(sorted(found.items())),
            "count": total,
        },
    )


SYMBOL = Symbol(
    id="sanitary",
    name="Sanitary fittings",
    kind="sanitary",
    detect=detect,
    scope="room",
    priority=10,
    description="Closed outlines matching standard bath, shower, WC, bidet or basin sizes.",
)


_BATHROOM = [(0, 0), (2400, 0), (2400, 1800), (0, 1800)]
_BIG_ROOM = [(0, 0), (8000, 0), (8000, 6000), (0, 6000)]


def _box(x: float, y: float, w: float, h: float, angle: float = 0.0):
    c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    pts = [(0.0, 0.0), (w, 0.0), (w, h), (0.0, h), (0.0, 0.0)]
    return [(x + px * c - py * s, y + px * s + py * c) for px, py in pts]


FIXTURES = [
    Fixture(
        name="bath, WC and basin in a 4 m2 bathroom",
        polygon=_BATHROOM,
        strokes=[
            _box(50, 50, 1700, 750),
            _box(1900, 100, 700, 400),
            _box(1900, 1200, 550, 420),
        ],
        expect=True,
    ),
    Fixture(
        name="a single WC still counts",
        polygon=_BATHROOM,
        strokes=[_box(200, 200, 700, 400)],
        expect=True,
    ),
    Fixture(
        name="a bath drawn at 30 degrees is still 1700 by 750",
        polygon=_BATHROOM,
        strokes=[_box(200, 200, 1700, 750, angle=30)],
        expect=True,
    ),
    Fixture(
        name="a square shower tray",
        polygon=_BATHROOM,
        strokes=[_box(100, 100, 900, 900)],
        expect=True,
    ),
    Fixture(
        name="an empty bathroom",
        polygon=_BATHROOM,
        strokes=[],
        expect=False,
    ),
    Fixture(
        name="a sofa is nothing in the catalogue",
        polygon=_BATHROOM,
        strokes=[_box(100, 100, 2100, 900)],
        expect=False,
    ),
    Fixture(
        name="open outlines are not fittings",
        polygon=_BATHROOM,
        strokes=[[(50, 50), (1750, 50), (1750, 800)]],
        expect=False,
    ),
    Fixture(
        name="a bath-sized object in a 48 m2 living room is furniture",
        polygon=_BIG_ROOM,
        strokes=[_box(500, 500, 1700, 750)],
        expect=False,
    ),
]
