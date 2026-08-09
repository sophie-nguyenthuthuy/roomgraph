"""Corner window: glazing that wraps a building corner, with no corner left.

This symbol only ever sees openings the wall stage had to *reconstruct*. A
corner window deletes the corner: both walls stop short, so there is no face
gap to find and, left alone, the room never encloses. `walls.bridge_corners`
puts the corner back and marks the length it invented as a bridged opening --
one on each of the two walls.

So the question here is not "is there a hole", it is "was that reconstructed
corner glazed". Evidence: glazing running the length of the opening, plus a
long return turning the corner at the jamb that sits on the wall's end.

Requiring `ctx.bridged` is what keeps this safe. Without it, the face lines of
any perpendicular wall look exactly like a corner return.
"""

from __future__ import annotations

from ..geom import Pt, Seg, dist, is_parallel
from . import Fixture, Match, OpeningContext, Symbol, along_wall, arc_points, coverage_of

MIN_ALONG_COVERAGE = 0.5
MIN_RETURN_ABS = 400.0        # a jamb cap is one wall thickness; a return is much longer
RETURN_NEAR_JAMB = 0.35       # fraction of the opening width
PERP_TOL_DEG = 12.0


def _segments(ctx: OpeningContext) -> list[Seg]:
    out: list[Seg] = []
    for pts in ctx.strokes:
        for i in range(len(pts) - 1):
            if dist(pts[i], pts[i + 1]) > 1.0:
                out.append(Seg(pts[i], pts[i + 1]))
    return out


def detect(ctx: OpeningContext) -> Match | None:
    if not ctx.bridged or ctx.width <= 0:
        return None
    side = ctx.flush_end()
    if side == 0:
        return None
    if ctx.arcs(min_span_deg=60.0):
        return None  # a swing in a bridged corner is a door, not glazing

    lo, hi = -ctx.width / 2.0, ctx.width / 2.0
    flush_x = side * ctx.width / 2.0
    min_return = max(MIN_RETURN_ABS, 2.0 * ctx.wall_thickness)
    near = max(RETURN_NEAR_JAMB * ctx.width, 2.0 * ctx.wall_thickness)

    # Collected across all strokes, not per stroke: exporters draw the L as one
    # polyline or as two separate lines, and both are common.
    along = [
        s for s in _segments(ctx)
        if along_wall(s, tol_deg=10.0) and coverage_of([s], lo, hi) >= MIN_ALONG_COVERAGE
    ]
    returns = [
        s for s in _segments(ctx)
        if is_parallel(s.vec, Pt(0.0, 1.0), tol_deg=PERP_TOL_DEG)
        and s.length() >= min_return
        and abs((s.a.x + s.b.x) / 2.0 - flush_x) <= near
    ]
    if not along or not returns:
        return None

    panes = min(len(along), len(returns))
    longest = max(s.length() for s in returns)

    conf = 0.88
    conf += 0.05 if panes >= 2 else 0.0
    conf += 0.04 * min(1.0, longest / max(ctx.width, 1.0))
    return Match(
        kind="window",
        confidence=min(0.97, conf),
        meta={
            "style": "corner",
            "leg_mm": round(ctx.width, 1),
            "return_mm": round(longest, 1),
            "glazing_lines": len(along),
            "note": "one opening per wall; the pair meets at a reconstructed corner",
        },
    )


SYMBOL = Symbol(
    id="window_corner",
    name="Corner window",
    kind="window",
    detect=detect,
    scope="opening",
    priority=40,
    description="Glazing wrapping a reconstructed corner, flush with the end of the wall.",
)


_LONG_WALL = {"wall_length": 7000.0, "t_mid": 6200.0, "bridged": True}

FIXTURES = [
    Fixture(
        name="corner glazing drawn as two L polylines",
        width=1600,
        wall_thickness=220,
        **_LONG_WALL,
        strokes=[
            [(-800, 110), (910, 110), (910, 1600)],
            [(-800, -110), (690, -110), (690, 1600)],
        ],
        expect=True,
    ),
    Fixture(
        name="same corner, legs and returns drawn as separate lines",
        width=1600,
        wall_thickness=220,
        **_LONG_WALL,
        strokes=[
            [(-800, 110), (910, 110)],
            [(-800, -110), (690, -110)],
            [(910, 110), (910, 1600)],
            [(690, -110), (690, 1600)],
        ],
        expect=True,
    ),
    Fixture(
        name="corner at the start of the wall instead of the end",
        width=1600,
        wall_thickness=220,
        wall_length=7000.0,
        t_mid=800.0,
        bridged=True,
        strokes=[
            [(800, 110), (-910, 110), (-910, 1600)],
            [(800, -110), (-690, -110), (-690, 1600)],
        ],
        expect=True,
    ),
    Fixture(
        name="bridged corner with no glazing at all is a plain opening",
        width=1600,
        wall_thickness=220,
        **_LONG_WALL,
        strokes=[],
        expect=False,
    ),
    Fixture(
        name="glazing but no return: a flat window at the wall end",
        width=1600,
        wall_thickness=220,
        **_LONG_WALL,
        strokes=[
            [(-800, 110), (800, 110)],
            [(-800, -110), (800, -110)],
        ],
        expect=False,
    ),
    Fixture(
        name="return is only a jamb cap, far too short",
        width=1600,
        wall_thickness=220,
        **_LONG_WALL,
        strokes=[
            [(-800, 110), (800, 110)],
            [(800, 110), (800, -110)],
        ],
        expect=False,
    ),
    Fixture(
        name="an ordinary face gap is never a corner window",
        width=1600,
        wall_thickness=220,
        wall_length=7000.0,
        t_mid=6200.0,
        bridged=False,
        strokes=[
            [(-800, 110), (910, 110), (910, 1600)],
            [(-800, -110), (690, -110), (690, 1600)],
        ],
        expect=False,
    ),
    Fixture(
        name="mid-wall opening is not flush with either end",
        width=1600,
        wall_thickness=220,
        wall_length=7000.0,
        t_mid=3500.0,
        bridged=True,
        strokes=[
            [(-800, 110), (910, 110), (910, 1600)],
            [(-800, -110), (690, -110), (690, 1600)],
        ],
        expect=False,
    ),
    Fixture(
        name="a door swing in a bridged corner is still a door",
        width=900,
        wall_thickness=110,
        wall_length=5000.0,
        t_mid=4550.0,
        bridged=True,
        strokes=[
            [(-450, 0), (-450, 900)],
            arc_points((-450, 0), 900, 90, 0),
        ],
        expect=False,
    ),
]
