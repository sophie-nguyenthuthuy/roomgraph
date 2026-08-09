"""Curtain walling: a long glazed run divided by regularly spaced mullions.

The glazing alone is just a window. What makes it curtain walling is the
*rhythm* -- mullions at a repeating module, typically 900 to 1800 mm, marching
the length of a wide opening.

Openings this wide only reach a detector at all because `walls.MAX_OPENING` is
generous. A wide gap with no glazing and no rhythm matches nothing and raises a
warning, which is the intended outcome for a wall someone forgot to draw.
"""

from __future__ import annotations

import statistics

from ..geom import Pt, is_parallel
from . import Fixture, Match, OpeningContext, Symbol, along_wall, coverage_of

MIN_RUN = 2500.0            # narrower than this is simply a window
MIN_GLAZING_LINES = 2
MIN_COVERAGE = 0.7
MIN_MULLIONS = 3
MODULE_RANGE = (600.0, 2200.0)
MAX_MODULE_SPREAD = 0.25    # coefficient of variation across mullion spacing
MULLION_MAX_LENGTH = 3.0    # as a multiple of wall thickness

# Curtain walling is strictly more specific than a flat window, and the two see
# the same glazing lines, so this sits at the window ceiling and rises above it.
BASE_CONFIDENCE = 0.92


def detect(ctx: OpeningContext) -> Match | None:
    if ctx.width < MIN_RUN:
        return None
    lo, hi = -ctx.width / 2.0, ctx.width / 2.0
    depth = max(ctx.wall_thickness * 1.3, 60.0)

    glazing = [
        s for s in ctx.straight_strokes(min_length=0.3 * ctx.width)
        if along_wall(s)
        and abs(s.midpoint().y) <= depth
        and coverage_of([s], lo, hi) >= MIN_COVERAGE
    ]
    if len(glazing) < MIN_GLAZING_LINES:
        return None

    max_mullion = max(MULLION_MAX_LENGTH * ctx.wall_thickness, 300.0)
    mullions = sorted(
        s.midpoint().x
        for s in ctx.straight_strokes(min_length=0.4 * ctx.wall_thickness)
        if is_parallel(s.vec, Pt(0.0, 1.0), tol_deg=12.0)
        and s.length() <= max_mullion
        # Mullions sit *in* the wall. Without this, a door jamb metres away
        # counts as one and wrecks the module spacing.
        and abs(s.midpoint().y) <= depth
        and lo + 1.0 < s.midpoint().x < hi - 1.0
    )
    # Two mullions drawn at the same station are one mullion.
    distinct: list[float] = []
    for x in mullions:
        if not distinct or x - distinct[-1] > 0.05 * ctx.width:
            distinct.append(x)
    if len(distinct) < MIN_MULLIONS:
        return None

    stations = [lo, *distinct, hi]
    modules = [b - a for a, b in zip(stations, stations[1:], strict=False)]
    mean = statistics.fmean(modules)
    if not (MODULE_RANGE[0] <= mean <= MODULE_RANGE[1]):
        return None
    spread = statistics.pstdev(modules) / mean if mean else 1.0
    if spread > MAX_MODULE_SPREAD:
        return None

    quality = (1.0 - spread / MAX_MODULE_SPREAD) * min(1.0, len(distinct) / 5.0)
    return Match(
        kind="window",
        confidence=min(0.97, BASE_CONFIDENCE + 0.05 * quality),
        meta={
            "style": "curtain_wall",
            "run_mm": round(ctx.width, 1),
            "mullions": len(distinct),
            "module_mm": round(mean, 1),
            "module_spread": round(spread, 3),
            "glazing_lines": len(glazing),
        },
    )


SYMBOL = Symbol(
    id="curtain_wall",
    name="Curtain walling",
    kind="window",
    detect=detect,
    scope="opening",
    priority=45,
    description="A wide glazed run divided by mullions at a regular module.",
)


def _curtain(run: float, mullions: int, thickness: float, glazing=(1, -1)):
    half = run / 2.0
    strokes = [[(-half, thickness / 2.0 * g), (half, thickness / 2.0 * g)] for g in glazing]
    step = run / (mullions + 1)
    for i in range(1, mullions + 1):
        x = -half + step * i
        strokes.append([(x, thickness / 2.0), (x, -thickness / 2.0)])
    return strokes


FIXTURES = [
    Fixture(
        name="6 m run on a 1200 mm module",
        width=6000,
        wall_thickness=200,
        strokes=_curtain(6000, 4, 200),
        expect=True,
    ),
    Fixture(
        name="3 m shopfront, three mullions",
        width=3000,
        wall_thickness=150,
        strokes=_curtain(3000, 3, 150),
        expect=True,
    ),
    Fixture(
        name="four glazing lines: still curtain walling, not a flat window",
        width=6000,
        wall_thickness=200,
        strokes=_curtain(6000, 4, 200, glazing=(1, 0.4, -0.4, -1)),
        expect=True,
        min_confidence=0.9,
    ),
    Fixture(
        name="a 1500 mm window is too narrow to be curtain walling",
        width=1500,
        wall_thickness=220,
        strokes=_curtain(1500, 3, 220),
        expect=False,
    ),
    Fixture(
        name="wide glazing with no mullions is just a big window",
        width=6000,
        wall_thickness=200,
        strokes=[[(-3000, 100), (3000, 100)], [(-3000, -100), (3000, -100)]],
        expect=False,
    ),
    Fixture(
        name="mullions at irregular stations",
        width=6000,
        wall_thickness=200,
        strokes=[
            [(-3000, 100), (3000, 100)],
            [(-3000, -100), (3000, -100)],
            [(-2600, 100), (-2600, -100)],
            [(-400, 100), (-400, -100)],
            [(2500, 100), (2500, -100)],
        ],
        expect=False,
    ),
    Fixture(
        name="a wide empty gap is a missing wall, not glazing",
        width=6000,
        wall_thickness=200,
        strokes=[],
        expect=False,
    ),
]
