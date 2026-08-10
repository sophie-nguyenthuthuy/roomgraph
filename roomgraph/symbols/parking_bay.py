"""Parking bays: repeated car-sized rectangles.

One bay-shaped rectangle is a rug or a table. Bays come in rows, so this asks
for at least two of the same size, unless the room is already named as parking
-- in which case a single marked bay is what it looks like.
"""

from __future__ import annotations

import statistics

from ..geom import oriented_extent, polygon_area
from . import Fixture, Match, RoomContext, Symbol

BAY_LONG = (4200.0, 6500.0)
BAY_SHORT = (2100.0, 3700.0)   # up to 3600 for an accessible bay with its transfer zone
MAX_SIZE_SPREAD = 0.12
ACCESSIBLE_SHORT = 3000.0   # a bay this wide is a designated accessible space


def detect(ctx: RoomContext) -> Match | None:
    bays: list[tuple[float, float]] = []
    for loop in ctx.loops():
        if abs(polygon_area(loop)) / 1e6 < 8.0:
            continue
        long_side, short_side = oriented_extent(loop)
        if not (BAY_LONG[0] <= long_side <= BAY_LONG[1]):
            continue
        if not (BAY_SHORT[0] <= short_side <= BAY_SHORT[1]):
            continue
        bays.append((long_side, short_side))

    if not bays:
        return None
    in_a_car_park = ctx.category == "garage"
    if len(bays) < 2 and not in_a_car_park:
        return None

    longs = [b[0] for b in bays]
    spread = statistics.pstdev(longs) / statistics.fmean(longs) if len(longs) > 1 else 0.0
    if spread > MAX_SIZE_SPREAD:
        return None  # rectangles of assorted sizes are furniture, not bays

    accessible = sum(1 for _, short in bays if short >= ACCESSIBLE_SHORT)
    conf = 0.66 + 0.08 * min(2, len(bays) - 1) + (0.10 if in_a_car_park else 0.0)
    return Match(
        kind="parking",
        confidence=min(0.92, conf),
        meta={
            "bays": len(bays),
            "accessible_bays": accessible,
            "bay_mm": [round(statistics.median(longs), 1),
                       round(statistics.median([b[1] for b in bays]), 1)],
        },
    )


SYMBOL = Symbol(
    id="parking_bay",
    name="Parking bays",
    kind="parking",
    detect=detect,
    scope="room",
    priority=10,
    description="Two or more car-sized rectangles of matching size.",
)


_GARAGE = [(0, 0), (16000, 0), (16000, 7000), (0, 7000)]


def _bay(x, y, w, h):
    return [(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)]


FIXTURES = [
    Fixture(
        name="a row of four 5000 by 2500 bays",
        polygon=_GARAGE,
        strokes=[_bay(500 + 2600 * i, 500, 5000, 2500) for i in range(4)],
        expect=True,
    ),
    Fixture(
        name="two bays, one of them accessible",
        polygon=_GARAGE,
        strokes=[_bay(500, 500, 5000, 2500), _bay(500, 3200, 5000, 3400)],
        expect=True,
    ),
    Fixture(
        name="a single bay in a room named as a garage",
        polygon=_GARAGE,
        category="garage",
        strokes=[_bay(500, 500, 5000, 2500)],
        expect=True,
    ),
    Fixture(
        name="a single bay-shaped rectangle elsewhere is furniture",
        polygon=_GARAGE,
        strokes=[_bay(500, 500, 5000, 2500)],
        expect=False,
    ),
    Fixture(
        name="rectangles of assorted sizes are not a bay row",
        polygon=_GARAGE,
        strokes=[_bay(500, 500, 4400, 2200), _bay(6000, 500, 6400, 3100)],
        expect=False,
    ),
    Fixture(
        name="an empty garage",
        polygon=_GARAGE,
        strokes=[],
        expect=False,
    ),
]
