"""Stair flight: a run of evenly spaced parallel treads inside a room.

A room-scope symbol rather than an opening one. It changes how a space should
be read -- a 4 m2 face full of treads is circulation, not a box room -- and it
demonstrates the second detector scope for contributors.
"""

from __future__ import annotations

import math
import statistics

from ..geom import Pt, angle_of, is_parallel
from . import Fixture, Match, RoomContext, Symbol

MIN_TREADS = 3
TREAD_SPACING = (200.0, 400.0)   # mm, going per step
TREAD_LENGTH = (600.0, 2400.0)   # mm, stair width
MAX_SPACING_CV = 0.30            # coefficient of variation across the run


def detect(ctx: RoomContext) -> Match | None:
    segs = [s for s in ctx.straight_strokes(min_length=TREAD_LENGTH[0]) if s.length() <= TREAD_LENGTH[1]]
    if len(segs) < MIN_TREADS:
        return None

    # Group by direction, then look for even spacing perpendicular to it.
    groups: list[list] = []
    for s in segs:
        for g in groups:
            if is_parallel(g[0].vec, s.vec, tol_deg=5.0):
                g.append(s)
                break
        else:
            groups.append([s])

    best: Match | None = None
    for g in groups:
        if len(g) < MIN_TREADS:
            continue
        d = g[0].dir()
        n = Pt(-d.y, d.x)
        offsets = sorted(s.midpoint().dot(n) for s in g)
        gaps = [b - a for a, b in zip(offsets, offsets[1:], strict=False) if b - a > 1e-6]
        if len(gaps) < MIN_TREADS - 1:
            continue
        mean = statistics.fmean(gaps)
        if not (TREAD_SPACING[0] <= mean <= TREAD_SPACING[1]):
            continue
        cv = (statistics.pstdev(gaps) / mean) if mean else 1.0
        if cv > MAX_SPACING_CV:
            continue

        conf = 0.55 + 0.25 * min(1.0, (len(g) - MIN_TREADS) / 6.0) + 0.15 * (1.0 - cv / MAX_SPACING_CV)
        if best is None or conf > best.confidence:
            best = Match(
                kind="stairs",
                confidence=min(0.95, conf),
                meta={
                    "treads": len(g),
                    "going_mm": round(mean, 1),
                    "flight_width_mm": round(statistics.fmean(s.length() for s in g), 1),
                    "direction_deg": round(math.degrees(angle_of(d)) % 180.0, 1),
                },
            )
    return best


SYMBOL = Symbol(
    id="stairs",
    name="Stair flight",
    kind="stairs",
    detect=detect,
    scope="room",
    priority=10,
    description="Three or more evenly spaced parallel treads within a room.",
)


_ROOM = [(0, 0), (3000, 0), (3000, 4000), (0, 4000)]

FIXTURES = [
    Fixture(
        name="10 treads at 270 mm going",
        polygon=_ROOM,
        strokes=[[(200, 300 + 270 * i), (1400, 300 + 270 * i)] for i in range(10)],
        expect=True,
    ),
    Fixture(
        name="minimum run of three treads",
        polygon=_ROOM,
        strokes=[[(200, 300 + 280 * i), (1400, 300 + 280 * i)] for i in range(3)],
        expect=True,
    ),
    Fixture(
        name="empty room",
        polygon=_ROOM,
        strokes=[],
        expect=False,
    ),
    Fixture(
        name="unevenly spaced lines are not a flight",
        polygon=_ROOM,
        strokes=[
            [(200, 300), (1400, 300)],
            [(200, 900), (1400, 900)],
            [(200, 1000), (1400, 1000)],
            [(200, 2400), (1400, 2400)],
        ],
        expect=False,
    ),
    Fixture(
        name="floor tile hatching is spaced too widely",
        polygon=_ROOM,
        strokes=[[(200, 300 + 600 * i), (1400, 300 + 600 * i)] for i in range(5)],
        expect=False,
    ),
]
