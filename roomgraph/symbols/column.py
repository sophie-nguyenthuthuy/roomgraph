"""Structural column: a small poched square or circle standing in a room.

Two things separate a column from the furniture it resembles at a glance. It is
usually *filled* -- poche is how structure is drawn -- and where it is not, it
comes in a grid: columns arrive in twos and threes, never alone.

So a single unfilled 600 mm square is refused. That is a box, and calling it
structure would put a load path into the model that the drawing never claimed.
"""

from __future__ import annotations

import math
import statistics

from ..geom import bbox, oriented_extent, polygon_area
from . import Fixture, Match, RoomContext, Symbol

SIZE_RANGE = (200.0, 800.0)
MAX_ASPECT = 1.6
MIN_AREA = 0.03   # m2
MAX_AREA = 0.72   # m2

# Columns stand apart; kitchen units of the same size abut in a run. Requiring
# clear space around each candidate is what separates the two, and it is also
# just true of structure.
ISOLATION = 1.2   # clear distance required, as a multiple of the column size


def _box_gap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    """Clear distance between two axis-aligned boxes; 0 when they touch or overlap."""
    dx = max(b[0] - a[2], a[0] - b[2], 0.0)
    dy = max(b[1] - a[3], a[1] - b[3], 0.0)
    return math.hypot(dx, dy)


def detect(ctx: RoomContext) -> Match | None:
    candidates: list[tuple[float, tuple[float, float, float, float], bool]] = []
    for index, loop in enumerate(ctx.strokes):
        if len(loop) < 4:
            continue
        area = abs(polygon_area(loop)) / 1e6
        if not (MIN_AREA <= area <= MAX_AREA):
            continue
        long_side, short_side = oriented_extent(loop)
        if short_side <= 0 or long_side / short_side > MAX_ASPECT:
            continue
        if not (SIZE_RANGE[0] <= long_side <= SIZE_RANGE[1]):
            continue
        candidates.append((long_side, bbox(loop), ctx.is_filled(index)))

    sizes: list[float] = []
    filled_count = 0
    for size, box, is_filled in candidates:
        clear = ISOLATION * size
        crowded = any(
            _box_gap(box, other) < clear for _, other, _ in candidates if other is not box
        )
        if crowded:
            continue
        sizes.append(size)
        if is_filled:
            filled_count += 1

    if not sizes:
        return None
    if filled_count == 0 and len(sizes) < 2:
        return None  # one unfilled box is a box, not a column

    conf = 0.62
    conf += 0.18 if filled_count else 0.0
    conf += 0.08 * min(1.0, (len(sizes) - 1) / 3.0)
    return Match(
        kind="column",
        confidence=min(0.92, conf),
        meta={
            "columns": len(sizes),
            "filled": filled_count,
            "size_mm": round(statistics.median(sizes), 1),
        },
    )


SYMBOL = Symbol(
    id="column",
    name="Structural column",
    kind="column",
    detect=detect,
    scope="room",
    priority=10,
    description="Small square or circular outlines, poched or repeating on a grid.",
)


_ROOM = [(0, 0), (9000, 0), (9000, 7000), (0, 7000)]


def _sq(x, y, size):
    return [(x, y), (x + size, y), (x + size, y + size), (x, y + size), (x, y)]


FIXTURES = [
    Fixture(
        name="three columns on a grid",
        polygon=_ROOM,
        strokes=[_sq(2000, 2000, 500), _sq(5000, 2000, 500), _sq(2000, 5000, 500)],
        expect=True,
    ),
    Fixture(
        name="a single poched column",
        polygon=_ROOM,
        strokes=[_sq(2000, 2000, 600)],
        filled=[True],
        expect=True,
    ),
    Fixture(
        name="a single unfilled box is not structure",
        polygon=_ROOM,
        strokes=[_sq(2000, 2000, 600)],
        expect=False,
    ),
    Fixture(
        name="a 2 m square is a room, not a column",
        polygon=_ROOM,
        strokes=[_sq(2000, 2000, 2000), _sq(5000, 2000, 2000)],
        expect=False,
    ),
    Fixture(
        name="a long thin outline is a wall or a worktop",
        polygon=_ROOM,
        strokes=[
            [(2000, 2000), (4000, 2000), (4000, 2400), (2000, 2400), (2000, 2000)],
            [(5000, 2000), (7000, 2000), (7000, 2400), (5000, 2400), (5000, 2000)],
        ],
        expect=False,
    ),
    Fixture(
        name="an empty room",
        polygon=_ROOM,
        strokes=[],
        expect=False,
    ),
]
