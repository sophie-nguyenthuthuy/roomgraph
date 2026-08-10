"""Laboratory benching: a run of units at bench depth.

Same idea as `kitchen` and deliberately the same shape of test, because a lab
is a fitted room too. What differs is the depth. Kitchen units are 600; wall
benches are 750 or 900, and island benches are 1500 to 1800 because they are
worked from both sides. The ranges are kept apart so the two symbols can never
claim the same run.

An island is the stronger evidence of the two: nothing in a dwelling is
1800 mm deep and 4 m long.
"""

from __future__ import annotations

import math
import statistics

from ..geom import oriented_extent, polygon_area
from . import Fixture, Match, RoomContext, Symbol

WALL_BENCH_DEPTH = (730.0, 980.0)     # above kitchen's 720 ceiling, deliberately
ISLAND_DEPTH = (1500.0, 1900.0)   # below 1500 is extract-canopy territory
WALL_BENCH_LENGTH = (900.0, 8000.0)
# An island seats several positions, so it is long. Without this floor a
# 2400 by 1600 air handling unit is island-shaped.
ISLAND_LENGTH = (3000.0, 9000.0)
MAX_DEPTH_SPREAD = 0.15
MIN_UNIT_AREA = 0.5   # m2


def _classify(long_side: float, short_side: float) -> str | None:
    if WALL_BENCH_DEPTH[0] <= short_side <= WALL_BENCH_DEPTH[1]:
        if WALL_BENCH_LENGTH[0] <= long_side <= WALL_BENCH_LENGTH[1]:
            return "wall_bench"
    if ISLAND_DEPTH[0] <= short_side <= ISLAND_DEPTH[1]:
        if ISLAND_LENGTH[0] <= long_side <= ISLAND_LENGTH[1]:
            return "island"
    return None


def detect(ctx: RoomContext) -> Match | None:
    if ctx.category in ("technical", "kitchen"):
        return None   # a plant room holds equipment; a kitchen has its own symbols

    benches: dict[str, list[float]] = {"wall_bench": [], "island": []}
    lengths: list[float] = []
    for loop in ctx.loops():
        if abs(polygon_area(loop)) / 1e6 < MIN_UNIT_AREA:
            continue
        long_side, short_side = oriented_extent(loop)
        kind = _classify(long_side, short_side)
        if kind:
            benches[kind].append(short_side)
            lengths.append(long_side)

    islands = len(benches["island"])
    walls = len(benches["wall_bench"])
    if islands + walls == 0:
        return None
    in_a_lab = ctx.category == "lab"
    if islands == 0 and walls < 2 and not in_a_lab:
        return None   # a single 900 deep box is a counter, a desk, a sideboard

    depths = benches["wall_bench"] or benches["island"]
    spread = (
        statistics.pstdev(depths) / statistics.fmean(depths) if len(depths) > 1 else 0.0
    )
    if spread > MAX_DEPTH_SPREAD:
        return None

    conf = 0.58
    conf += 0.14 if islands else 0.0
    conf += 0.08 * min(2, walls - 1) if walls else 0.0
    conf += 0.12 if in_a_lab else 0.0
    return Match(
        kind="lab_bench",
        confidence=min(0.93, conf),
        meta={
            "wall_benches": walls,
            "islands": islands,
            "depth_mm": round(statistics.median(depths), 1),
            "run_mm": round(sum(lengths), 1),
        },
    )


SYMBOL = Symbol(
    id="lab_bench",
    name="Laboratory benching",
    kind="lab_bench",
    detect=detect,
    scope="room",
    priority=12,
    description="Runs at bench depth (750-900) or island depth (1500-1800).",
)


_LAB = [(0, 0), (9000, 0), (9000, 7000), (0, 7000)]


def _box(x, y, w, h, angle=0.0):
    c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    pts = [(0.0, 0.0), (w, 0.0), (w, h), (0.0, h), (0.0, 0.0)]
    return [(x + px * c - py * s, y + px * s + py * c) for px, py in pts]


FIXTURES = [
    Fixture(
        name="two wall benches at 750 deep",
        polygon=_LAB,
        strokes=[_box(200, 200, 3000, 750), _box(3400, 200, 2400, 750)],
        expect=True,
    ),
    Fixture(
        name="a single island bench",
        polygon=_LAB,
        strokes=[_box(2000, 3000, 4000, 1800)],
        expect=True,
    ),
    Fixture(
        name="one wall bench in a room named as a laboratory",
        polygon=_LAB,
        category="lab",
        strokes=[_box(200, 200, 3000, 900)],
        expect=True,
    ),
    Fixture(
        name="600 deep units are a kitchen, not a lab",
        polygon=_LAB,
        strokes=[_box(200, 200, 1800, 600), _box(2100, 200, 600, 600)],
        expect=False,
    ),
    Fixture(
        name="a lone 900 deep counter says nothing",
        polygon=_LAB,
        strokes=[_box(200, 200, 3000, 900)],
        expect=False,
    ),
    Fixture(
        name="an air handling unit is not an island bench",
        polygon=_LAB,
        strokes=[_box(300, 300, 2400, 1600), _box(3200, 300, 2400, 1600)],
        expect=False,
    ),
    Fixture(
        name="benching is not looked for in a plant room",
        polygon=_LAB,
        category="technical",
        strokes=[_box(200, 200, 3000, 750), _box(3400, 200, 2400, 750)],
        expect=False,
    ),
    Fixture(
        name="an empty laboratory",
        polygon=_LAB,
        category="lab",
        strokes=[],
        expect=False,
    ),
]
