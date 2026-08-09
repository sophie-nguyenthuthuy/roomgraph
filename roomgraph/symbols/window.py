"""Window: parallel glazing lines running the length of the opening.

Two lines for single glazing, three or four for a framed or double-glazed unit.
They sit inside the wall thickness and span nearly the whole opening, which is
what separates them from a sliding leaf (one line, offset to one side).
"""

from __future__ import annotations

from . import Fixture, Match, OpeningContext, Symbol, along_wall, coverage_of

MIN_COVERAGE = 0.55
DEPTH_RATIO = 1.1  # glazing must stay within this multiple of the half-thickness


def _glazing_lines(ctx: OpeningContext) -> list[tuple[float, float]]:
    """Returns (offset_y, coverage) for each stroke running along the opening."""
    lo, hi = -ctx.width / 2.0, ctx.width / 2.0
    depth = max(ctx.wall_thickness * DEPTH_RATIO, 40.0)
    out: list[tuple[float, float]] = []
    for s in ctx.straight_strokes(min_length=0.3 * ctx.width):
        if not along_wall(s):
            continue
        y = (s.a.y + s.b.y) / 2.0
        if abs(y) > depth:
            continue
        cov = coverage_of([s], lo, hi)
        if cov >= MIN_COVERAGE:
            out.append((y, cov))
    return out


def detect(ctx: OpeningContext) -> Match | None:
    if ctx.width <= 0:
        return None
    lines = _glazing_lines(ctx)
    if len(lines) < 2:
        return None

    # A sliding leaf gives one line to one side; glazing straddles the centre
    # or comes in three or more.
    straddles = any(y >= -1e-6 for y, _ in lines) and any(y <= 1e-6 for y, _ in lines)
    if len(lines) < 3 and not straddles:
        return None

    coverage = sum(c for _, c in lines) / len(lines)
    conf = 0.55 + 0.10 * min(2, len(lines) - 2) + 0.25 * min(1.0, coverage)
    return Match(
        kind="window",
        confidence=min(0.95, conf),
        meta={
            "glazing_lines": len(lines),
            "coverage": round(coverage, 3),
            "sill_width_mm": round(ctx.width, 1),
        },
    )


SYMBOL = Symbol(
    id="window",
    name="Window",
    kind="window",
    detect=detect,
    scope="opening",
    priority=10,
    description="Two or more parallel glazing lines spanning the opening inside the wall.",
)


FIXTURES = [
    Fixture(
        name="1500 mm window, three glazing lines",
        width=1500,
        wall_thickness=220,
        strokes=[
            [(-750, 110), (750, 110)],
            [(-750, 0), (750, 0)],
            [(-750, -110), (750, -110)],
        ],
        expect=True,
    ),
    Fixture(
        name="1200 mm window, two lines straddling the centre",
        width=1200,
        wall_thickness=220,
        strokes=[
            [(-600, 60), (600, 60)],
            [(-600, -60), (600, -60)],
        ],
        expect=True,
    ),
    Fixture(
        name="door swing is not a window",
        width=900,
        strokes=[
            [(-450, 0), (-450, 900)],
            [(-450, 0), (450, 0)],
        ],
        expect=False,
    ),
    Fixture(
        name="single sliding leaf offset to one side",
        width=1200,
        wall_thickness=110,
        strokes=[[(-600, 60), (600, 60)]],
        expect=False,
    ),
    Fixture(
        name="lines too short to be glazing",
        width=1500,
        wall_thickness=220,
        strokes=[
            [(-750, 110), (-500, 110)],
            [(-750, -110), (-500, -110)],
        ],
        expect=False,
    ),
    Fixture(name="empty opening", width=1500, strokes=[], expect=False),
]
