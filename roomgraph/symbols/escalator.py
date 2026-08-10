"""Escalator: a long stepped band running between two balustrades.

The steps alone are indistinguishable from a straight stair flight -- same
spacing, same parallel treads. The balustrades are what settle it: two long
lines running the *length* of the band, spanning the whole run, which a stair
flight does not have.

Length settles the rest. A domestic flight is two or three metres; an escalator
is eight or more, and this asks for at least four.
"""

from __future__ import annotations

import statistics

from ..geom import Pt, Seg, is_parallel
from . import Fixture, Match, RoomContext, Symbol

MIN_STEPS = 8
STEP_SPACING = (280.0, 520.0)
STEP_WIDTH = (700.0, 1900.0)
MAX_SPACING_SPREAD = 0.22
MIN_RUN = 4000.0
# Longer than any single escalator flight: that is a travelator, and this
# symbol stands down rather than both of them reporting the same band.
MAX_RUN = 16000.0
BALUSTRADE_COVERAGE = 0.75


def detect(ctx: RoomContext) -> Match | None:
    segs = ctx.straight_strokes(min_length=200.0)
    if len(segs) < MIN_STEPS + 2:
        return None

    groups: list[list[Seg]] = []
    for s in segs:
        for g in groups:
            if is_parallel(g[0].vec, s.vec, tol_deg=5.0):
                g.append(s)
                break
        else:
            groups.append([s])

    best: Match | None = None
    for steps in groups:
        treads = [s for s in steps if STEP_WIDTH[0] <= s.length() <= STEP_WIDTH[1]]
        if len(treads) < MIN_STEPS:
            continue
        d = treads[0].dir()
        n = Pt(-d.y, d.x)
        offsets = sorted(s.midpoint().dot(n) for s in treads)
        gaps = [b - a for a, b in zip(offsets, offsets[1:], strict=False) if b - a > 1.0]
        if len(gaps) < MIN_STEPS - 1:
            continue
        mean_gap = statistics.fmean(gaps)
        if not (STEP_SPACING[0] <= mean_gap <= STEP_SPACING[1]):
            continue
        if statistics.pstdev(gaps) / mean_gap > MAX_SPACING_SPREAD:
            continue
        run = offsets[-1] - offsets[0]
        if not (MIN_RUN <= run <= MAX_RUN):
            continue

        # Balustrades run the length of the band, perpendicular to the steps.
        rails = [
            s for s in segs
            if is_parallel(s.vec, n, tol_deg=8.0) and s.length() >= BALUSTRADE_COVERAGE * run
        ]
        if len(rails) < 2:
            continue

        conf = 0.80 + 0.08 * min(1.0, (len(treads) - MIN_STEPS) / 12.0)
        conf += 0.06 * min(1.0, run / 12000.0)
        match = Match(
            kind="escalator",
            confidence=min(0.94, conf),
            meta={
                "steps": len(treads),
                "run_mm": round(run, 1),
                "going_mm": round(mean_gap, 1),
                "width_mm": round(statistics.fmean(s.length() for s in treads), 1),
                "balustrades": len(rails),
            },
        )
        if best is None or match.confidence > best.confidence:
            best = match
    return best


SYMBOL = Symbol(
    id="escalator",
    name="Escalator",
    kind="escalator",
    detect=detect,
    scope="room",
    priority=30,
    description="A long run of steps between two full-length balustrades.",
)


_HALL = [(0, 0), (6000, 0), (6000, 14000), (0, 14000)]


def _escalator(x, y, width, steps, going, rails=True):
    out = [[(x, y + going * i), (x + width, y + going * i)] for i in range(steps)]
    if rails:
        run = going * (steps - 1)
        out.append([(x, y), (x, y + run)])
        out.append([(x + width, y), (x + width, y + run)])
    return out


FIXTURES = [
    Fixture(
        name="a 24 step escalator with both balustrades",
        polygon=_HALL,
        strokes=_escalator(1000, 500, 1200, 24, 400),
        expect=True,
    ),
    Fixture(
        name="the minimum: eight steps over four metres",
        polygon=_HALL,
        strokes=_escalator(1000, 500, 1000, 11, 420),
        expect=True,
    ),
    Fixture(
        name="a stair flight has no balustrades running its length",
        polygon=_HALL,
        strokes=_escalator(1000, 500, 1200, 24, 400, rails=False),
        expect=False,
    ),
    Fixture(
        name="too short to be an escalator",
        polygon=_HALL,
        strokes=_escalator(1000, 500, 1200, 9, 300),
        expect=False,
    ),
    Fixture(
        name="steps spaced like floor tiles, far too wide apart",
        polygon=_HALL,
        strokes=_escalator(1000, 500, 1200, 12, 900),
        expect=False,
    ),
    Fixture(
        name="a 20 m run is a travelator, not an escalator",
        polygon=[(0, 0), (6000, 0), (6000, 26000), (0, 26000)],
        strokes=_escalator(1000, 500, 1200, 51, 400),
        expect=False,
    ),
    Fixture(
        name="an empty hall",
        polygon=_HALL,
        strokes=[],
        expect=False,
    ),
]
