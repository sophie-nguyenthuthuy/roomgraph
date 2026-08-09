"""Spiral stair: treads radiating from a central newel.

The room-scope cousin of `door_revolving` -- both are wheels -- but told apart
by where they live and how many spokes they have. A revolving door has three or
four leaves inside a wall opening; a spiral stair has six or more treads inside
a room.

It cannot be confused with the straight-flight `stairs` symbol either: that one
wants parallel treads at even spacing, and these are parallel to nothing.
"""

from __future__ import annotations

import math
import statistics

from ..geom import Pt, angle_of, dist
from . import Fixture, Match, RoomContext, Symbol

MIN_TREADS = 6
MAX_TREADS = 30
TREAD_LENGTH = (450.0, 2200.0)   # newel to outer string
NEWEL_TOL = 260.0                # how tightly treads must share a centre
MAX_LENGTH_SPREAD = 0.15
MAX_ANGLE_SPREAD = 0.45          # spacing is coarser than a revolving door's


def _hub_candidates(segs) -> list[Pt]:
    return [s.a for s in segs] + [s.b for s in segs]


def detect(ctx: RoomContext) -> Match | None:
    segs = [
        s for s in ctx.straight_strokes(min_length=TREAD_LENGTH[0])
        if s.length() <= TREAD_LENGTH[1]
    ]
    if len(segs) < MIN_TREADS:
        return None

    best: Match | None = None
    for hub in _hub_candidates(segs):
        spokes: list[tuple[float, float]] = []   # (bearing, length)
        for s in segs:
            da, db = dist(s.a, hub), dist(s.b, hub)
            near, far = (s.a, s.b) if da <= db else (s.b, s.a)
            if dist(near, hub) > NEWEL_TOL:
                continue
            spokes.append((math.degrees(angle_of(far - hub)) % 360.0, s.length()))
        if not (MIN_TREADS <= len(spokes) <= MAX_TREADS):
            continue

        lengths = [ln for _, ln in spokes]
        mean_len = statistics.fmean(lengths)
        if mean_len <= 0 or statistics.pstdev(lengths) / mean_len > MAX_LENGTH_SPREAD:
            continue

        bearings = sorted(b for b, _ in spokes)
        gaps = [
            (bearings[(i + 1) % len(bearings)] - bearings[i]) % 360.0
            for i in range(len(bearings))
        ]
        # Drop the widest gap before measuring regularity. A stair that turns
        # less than a full circle leaves one big empty sector, and so does a
        # full one whose bearings straddle north -- neither is irregularity.
        sweep_gap = max(gaps)
        gaps.remove(sweep_gap)
        mean_gap = statistics.fmean(gaps)
        if mean_gap <= 0:
            continue
        spread = statistics.pstdev(gaps) / mean_gap
        if spread > MAX_ANGLE_SPREAD:
            continue

        conf = 0.66
        conf += 0.14 * min(1.0, (len(spokes) - MIN_TREADS) / 8.0)
        conf += 0.12 * (1.0 - spread / MAX_ANGLE_SPREAD)
        match = Match(
            kind="stairs",
            confidence=min(0.93, conf),
            meta={
                "form": "spiral",
                "treads": len(spokes),
                "radius_mm": round(mean_len, 1),
                "sweep_deg": round(mean_gap * len(gaps) + mean_gap, 1),
                "angle_spread": round(spread, 3),
            },
        )
        if best is None or match.confidence > best.confidence:
            best = match
    return best


SYMBOL = Symbol(
    id="stairs_spiral",
    name="Spiral stair",
    kind="stairs",
    detect=detect,
    scope="room",
    priority=20,
    description="Six or more treads radiating from a common newel inside a room.",
)


_ROOM = [(0, 0), (3000, 0), (3000, 3000), (0, 3000)]


def _spiral(centre, radius, treads, start=0.0, sweep=360.0):
    out = []
    for i in range(treads):
        a = math.radians(start + sweep * i / treads)
        out.append(
            [centre, (centre[0] + radius * math.cos(a), centre[1] + radius * math.sin(a))]
        )
    return out


FIXTURES = [
    Fixture(
        name="twelve treads around a full turn",
        polygon=_ROOM,
        strokes=_spiral((1500, 1500), 800, 12),
        expect=True,
    ),
    Fixture(
        name="nine treads over three quarters of a turn",
        polygon=_ROOM,
        strokes=_spiral((1500, 1500), 900, 9, sweep=270.0),
        expect=True,
    ),
    Fixture(
        name="the minimum run of six treads",
        polygon=_ROOM,
        strokes=_spiral((1400, 1400), 750, 6),
        expect=True,
    ),
    Fixture(
        name="a straight flight has parallel treads, not radial ones",
        polygon=_ROOM,
        strokes=[[(200, 300 + 270 * i), (1400, 300 + 270 * i)] for i in range(10)],
        expect=False,
    ),
    Fixture(
        name="four leaves is a revolving door, not a stair",
        polygon=_ROOM,
        strokes=_spiral((1500, 1500), 800, 4),
        expect=False,
    ),
    Fixture(
        name="radial lines of wildly differing length",
        polygon=_ROOM,
        strokes=[
            [(1500, 1500), (2000, 1500)],
            [(1500, 1500), (1500, 2400)],
            [(1500, 1500), (100, 1500)],
            [(1500, 1500), (1500, 900)],
            [(1500, 1500), (2900, 2900)],
            [(1500, 1500), (800, 1500)],
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
