"""Kitchen fittings: a run of units at a consistent depth.

Deliberately not a catalogue of appliances. A hob, an oven, a dishwasher and a
base unit are all a 600 mm square in plan, and guessing between them would be
invention. What *is* real and measurable is the run: several outlines sharing
one depth, which is the defining fact about fitted kitchens.

Depth is the signal. Kitchen units are 600 mm deep almost universally, and
nothing else in a dwelling lines up that way.
"""

from __future__ import annotations

import math
import statistics

from ..geom import oriented_extent, polygon_area
from . import Fixture, Match, RoomContext, Symbol

DEPTH_RANGE = (480.0, 720.0)     # nominal 600 plus worktop overhang and tolerance
UNIT_LENGTH = (350.0, 6000.0)
MAX_DEPTH_SPREAD = 0.16
MIN_UNIT_AREA = 0.10             # m2
MAX_ROOM_AREA_M2 = 60.0
MIN_RUN_ELEMENT = 900.0   # a run has at least one unit longer than this


def detect(ctx: RoomContext) -> Match | None:
    if ctx.category == "bathroom" or ctx.area_m2 > MAX_ROOM_AREA_M2:
        return None

    depths: list[float] = []
    lengths: list[float] = []
    for loop in ctx.loops():
        if abs(polygon_area(loop)) / 1e6 < MIN_UNIT_AREA:
            continue
        long_side, short_side = oriented_extent(loop)
        if not (DEPTH_RANGE[0] <= short_side <= DEPTH_RANGE[1]):
            continue
        if not (UNIT_LENGTH[0] <= long_side <= UNIT_LENGTH[1]):
            continue
        depths.append(short_side)
        lengths.append(long_side)

    if not depths:
        return None
    in_a_kitchen = ctx.category == "kitchen"
    if len(depths) < 2 and not in_a_kitchen:
        return None  # one 600 mm box on its own is just a box
    if max(lengths) < MIN_RUN_ELEMENT and not in_a_kitchen:
        # Scattered 500 mm squares are columns. A fitted run always contains
        # something longer -- a worktop, a sink base, a hob.
        return None

    spread = statistics.pstdev(depths) / statistics.fmean(depths) if len(depths) > 1 else 0.0
    if spread > MAX_DEPTH_SPREAD:
        return None

    conf = 0.58
    conf += 0.10 * min(2, len(depths) - 1)
    conf += 0.12 if in_a_kitchen else 0.0
    conf += 0.06 * (1.0 - spread / MAX_DEPTH_SPREAD)
    return Match(
        kind="kitchen",
        confidence=min(0.93, conf),
        meta={
            "units": len(depths),
            "depth_mm": round(statistics.median(depths), 1),
            "run_mm": round(sum(lengths), 1),
            "depth_spread": round(spread, 3),
        },
    )


SYMBOL = Symbol(
    id="kitchen",
    name="Kitchen fittings",
    kind="kitchen",
    detect=detect,
    scope="room",
    priority=10,
    description="Several unit outlines sharing one depth, the signature of a fitted run.",
)


_KITCHEN = [(0, 0), (4000, 0), (4000, 3000), (0, 3000)]


def _box(x, y, w, h, angle=0.0):
    c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    pts = [(0.0, 0.0), (w, 0.0), (w, h), (0.0, h), (0.0, 0.0)]
    return [(x + px * c - py * s, y + px * s + py * c) for px, py in pts]


FIXTURES = [
    Fixture(
        name="a run of four 600 mm units",
        polygon=_KITCHEN,
        category="kitchen",
        strokes=[
            _box(100, 100, 1800, 600),
            _box(1900, 100, 600, 600),
            _box(2500, 100, 600, 600),
            _box(3100, 100, 700, 600),
        ],
        expect=True,
    ),
    Fixture(
        name="two units is already a run",
        polygon=_KITCHEN,
        strokes=[_box(100, 100, 1200, 600), _box(1300, 100, 600, 600)],
        expect=True,
    ),
    Fixture(
        name="a single unit counts when the room is named as a kitchen",
        polygon=_KITCHEN,
        category="kitchen",
        strokes=[_box(100, 100, 1800, 600)],
        expect=True,
    ),
    Fixture(
        name="a run drawn at an angle is still 600 deep",
        polygon=_KITCHEN,
        strokes=[_box(200, 200, 1800, 600, angle=25), _box(2400, 200, 900, 600, angle=25)],
        expect=True,
    ),
    Fixture(
        name="scattered 500 mm squares are columns, not a fitted run",
        polygon=_KITCHEN,
        strokes=[_box(300, 300, 500, 500), _box(2500, 2000, 500, 500)],
        expect=False,
    ),
    Fixture(
        name="a single 600 mm box in an unnamed room is just a box",
        polygon=_KITCHEN,
        strokes=[_box(100, 100, 600, 600)],
        expect=False,
    ),
    Fixture(
        name="units of wildly different depths are furniture",
        polygon=_KITCHEN,
        strokes=[_box(100, 100, 1800, 600), _box(100, 900, 1800, 300)],
        expect=False,
    ),
    Fixture(
        name="a bathroom is not a kitchen",
        polygon=_KITCHEN,
        category="bathroom",
        strokes=[_box(100, 100, 1200, 600), _box(1300, 100, 600, 600)],
        expect=False,
    ),
    Fixture(
        name="an empty room",
        polygon=_KITCHEN,
        strokes=[],
        expect=False,
    ),
]
