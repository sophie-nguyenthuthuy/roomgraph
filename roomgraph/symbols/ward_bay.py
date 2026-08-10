"""Hospital bed bays: repeated beds at a regular pitch along a ward.

A single hospital bed is just a bed, and `furniture_layout` reports it as one.
What makes a ward is the repetition -- three or more beds of the same size at
an even pitch, which is how bays are set out and dimensioned.

Both symbols report. That is not the redundancy that `stairs` and `escalator`
had, where one name for one object was wrong: here the ward is the room and the
beds are its contents, and both statements are true and separately useful.
"""

from __future__ import annotations

import statistics

from ..geom import Pt, oriented_extent, polygon_area
from . import Fixture, Match, RoomContext, Symbol

BED_LONG = (1800.0, 2300.0)
BED_SHORT = (800.0, 1200.0)
MIN_BEDS = 3
MAX_SIZE_SPREAD = 0.10
BAY_PITCH = (1800.0, 4200.0)
MAX_PITCH_SPREAD = 0.20


def detect(ctx: RoomContext) -> Match | None:
    beds: list[tuple[Pt, float]] = []
    for loop in ctx.loops():
        if abs(polygon_area(loop)) / 1e6 < 1.2:
            continue
        long_side, short_side = oriented_extent(loop)
        if not (BED_LONG[0] <= long_side <= BED_LONG[1]):
            continue
        if not (BED_SHORT[0] <= short_side <= BED_SHORT[1]):
            continue
        centre = Pt(
            sum(p.x for p in loop) / len(loop), sum(p.y for p in loop) / len(loop)
        )
        beds.append((centre, long_side))

    if len(beds) < MIN_BEDS:
        return None
    sizes = [s for _, s in beds]
    if statistics.pstdev(sizes) / statistics.fmean(sizes) > MAX_SIZE_SPREAD:
        return None

    pitch, spread = _pitch(beds)
    if pitch <= 0:
        return None

    conf = 0.68
    conf += 0.08 * min(2, len(beds) - MIN_BEDS)
    conf += 0.08 * (1.0 - min(1.0, spread / MAX_PITCH_SPREAD))
    conf += 0.08 if ctx.category == "ward" else 0.0
    return Match(
        kind="ward",
        confidence=min(0.92, conf),
        meta={
            "bays": len(beds),
            "bay_pitch_mm": round(pitch, 1),
            "bed_mm": round(statistics.median(sizes), 1),
        },
    )


def _pitch(beds: list[tuple[Pt, float]]) -> tuple[float, float]:
    for axis in (Pt(1.0, 0.0), Pt(0.0, 1.0)):
        positions = sorted(c.dot(axis) for c, _ in beds)
        gaps = [b - a for a, b in zip(positions, positions[1:], strict=False) if b - a > 1.0]
        if len(gaps) < MIN_BEDS - 1:
            continue
        mean = statistics.fmean(gaps)
        if not (BAY_PITCH[0] <= mean <= BAY_PITCH[1]):
            continue
        spread = statistics.pstdev(gaps) / mean if mean else 1.0
        if spread <= MAX_PITCH_SPREAD:
            return mean, spread
    return 0.0, 1.0


SYMBOL = Symbol(
    id="ward_bay",
    name="Hospital bed bays",
    kind="ward",
    detect=detect,
    scope="room",
    priority=18,
    description="Three or more beds of one size at a regular bay pitch.",
)


_WARD = [(0, 0), (14000, 0), (14000, 7000), (0, 7000)]


def _bed(x, y, w=1000, d=2100):
    return [(x, y), (x + w, y), (x + w, y + d), (x, y + d), (x, y)]


FIXTURES = [
    Fixture(
        name="four bays at a 3 m pitch",
        polygon=_WARD,
        category="ward",
        strokes=[_bed(600 + 3000 * i, 400) for i in range(4)],
        expect=True,
    ),
    Fixture(
        name="three bays, unnamed room",
        polygon=_WARD,
        strokes=[_bed(600 + 2600 * i, 400) for i in range(3)],
        expect=True,
    ),
    Fixture(
        name="two beds is a bedroom, not a ward",
        polygon=_WARD,
        strokes=[_bed(600, 400), _bed(3600, 400)],
        expect=False,
    ),
    Fixture(
        name="beds at wildly irregular spacing",
        polygon=_WARD,
        strokes=[_bed(600, 400), _bed(1800, 400), _bed(9000, 400)],
        expect=False,
    ),
    Fixture(
        name="an empty ward",
        polygon=_WARD,
        category="ward",
        strokes=[],
        expect=False,
    ),
]
