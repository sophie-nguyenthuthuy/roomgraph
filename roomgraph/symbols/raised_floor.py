"""Raised access floor: a 600 mm tile grid over the room.

Two families of evenly spaced lines crossing at right angles, at the tile
module. The pitch is what identifies it and also what keeps it clear of the
stair symbol, which wants 200 to 400 -- a going nobody could climb at 600.

A drawing that only annotates the floor without hatching it is not detected.
The tiles have to be drawn.
"""

from __future__ import annotations

import statistics

from ..geom import Pt, is_parallel
from . import Fixture, Match, RoomContext, Symbol

TILE_PITCH = (450.0, 750.0)     # 600 nominal
MIN_LINES_PER_AXIS = 4
MAX_PITCH_SPREAD = 0.15
MIN_COVERAGE = 0.5              # of the room's shorter side


def _axis_lines(ctx: RoomContext, axis: Pt, min_length: float) -> list[float]:
    normal = axis.perp()
    positions = [
        s.midpoint().dot(normal)
        for s in ctx.straight_strokes(min_length=min_length)
        if is_parallel(s.vec, axis, tol_deg=4.0)
    ]
    distinct: list[float] = []
    for v in sorted(positions):
        if not distinct or v - distinct[-1] > 50.0:
            distinct.append(v)
    return distinct


def detect(ctx: RoomContext) -> Match | None:
    xs = [p.x for p in ctx.polygon]
    ys = [p.y for p in ctx.polygon]
    if not xs or not ys:
        return None
    span_x, span_y = max(xs) - min(xs), max(ys) - min(ys)
    reach = MIN_COVERAGE * min(span_x, span_y)
    if reach <= 0:
        return None

    pitches: list[float] = []
    counts: list[int] = []
    for axis in (Pt(1.0, 0.0), Pt(0.0, 1.0)):
        lines = _axis_lines(ctx, axis, reach)
        if len(lines) < MIN_LINES_PER_AXIS:
            return None
        gaps = [b - a for a, b in zip(lines, lines[1:], strict=False)]
        mean = statistics.fmean(gaps)
        if not (TILE_PITCH[0] <= mean <= TILE_PITCH[1]):
            return None
        if statistics.pstdev(gaps) / mean > MAX_PITCH_SPREAD:
            return None
        pitches.append(mean)
        counts.append(len(lines))

    pitch = statistics.fmean(pitches)
    conf = 0.70 + 0.10 * min(1.0, (min(counts) - MIN_LINES_PER_AXIS) / 6.0)
    conf += 0.08 if abs(pitch - 600.0) <= 40.0 else 0.0
    return Match(
        kind="raised_floor",
        confidence=min(0.90, conf),
        meta={
            "tile_mm": round(pitch, 1),
            "lines": counts,
        },
    )


SYMBOL = Symbol(
    id="raised_floor",
    name="Raised access floor",
    kind="raised_floor",
    detect=detect,
    scope="room",
    priority=8,
    description="A grid of tile joints at roughly 600 mm in both directions.",
)


_ROOM = [(0, 0), (6000, 0), (6000, 4800), (0, 4800)]


def _tiles(pitch=600.0, w=6000.0, h=4800.0):
    out = []
    x = pitch
    while x < w:
        out.append([(x, 0.0), (x, h)])
        x += pitch
    y = pitch
    while y < h:
        out.append([(0.0, y), (w, y)])
        y += pitch
    return out


FIXTURES = [
    Fixture(
        name="a 600 mm tile grid",
        polygon=_ROOM,
        strokes=_tiles(),
        expect=True,
    ),
    Fixture(
        name="a 500 mm module",
        polygon=_ROOM,
        strokes=_tiles(500.0),
        expect=True,
    ),
    Fixture(
        name="lines in one direction only is hatching",
        polygon=_ROOM,
        strokes=[s for s in _tiles() if s[0][0] == s[1][0]],
        expect=False,
    ),
    Fixture(
        name="a 300 mm pitch is a stair, not a floor",
        polygon=_ROOM,
        strokes=_tiles(300.0),
        expect=False,
    ),
    Fixture(
        name="an empty room",
        polygon=_ROOM,
        strokes=[],
        expect=False,
    ),
]
