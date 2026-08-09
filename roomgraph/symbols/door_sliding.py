"""Sliding / pocket door: a leaf drawn as a thin panel offset to one side.

No swing arc, so the leaf itself is the whole signal: one panel running parallel
to the wall, about as long as the opening, sitting off the centreline and often
overrunning a jamb into the pocket.
"""

from __future__ import annotations

from . import (
    Fixture,
    Match,
    OpeningContext,
    Symbol,
    along_wall,
    coverage_of,
    span_x,
)

LENGTH_RATIO = (0.70, 1.60)  # leaf length relative to the opening


def detect(ctx: OpeningContext) -> Match | None:
    if ctx.width <= 0:
        return None
    lo, hi = -ctx.width / 2.0, ctx.width / 2.0
    depth = max(ctx.wall_thickness * 1.6, 60.0)

    candidates = []
    for s in ctx.straight_strokes(min_length=LENGTH_RATIO[0] * ctx.width):
        if not along_wall(s):
            continue
        y = (s.a.y + s.b.y) / 2.0
        if abs(y) > depth:
            continue
        ratio = s.length() / ctx.width
        if not (LENGTH_RATIO[0] <= ratio <= LENGTH_RATIO[1]):
            continue
        if coverage_of([s], lo, hi) < 0.5:
            continue
        candidates.append((s, y, ratio))

    if not candidates:
        return None

    # Glazing straddling the wall centreline is a window, not a sliding leaf.
    offsets = [y for _, y, _ in candidates]
    if len(candidates) >= 2 and any(y > 1e-6 for y in offsets) and any(y < -1e-6 for y in offsets):
        return None
    if any(abs(y) < 0.15 * max(ctx.wall_thickness, 60.0) for y in offsets) and len(candidates) >= 2:
        return None

    seg, y, ratio = max(candidates, key=lambda c: c[0].length())
    a, b = span_x(seg)
    overrun = max(lo - a, b - hi, 0.0)

    conf = 0.50
    conf += 0.15 * max(0.0, 1.0 - abs(ratio - 1.0) / 0.6)
    conf += 0.15 * min(1.0, overrun / (0.25 * ctx.width))  # pocket overrun is telling
    conf += 0.10 * min(1.0, abs(y) / max(ctx.wall_thickness * 0.5, 30.0))
    return Match(
        kind="door",
        confidence=min(0.9, conf),
        meta={
            "leaf_width_mm": round(seg.length(), 1),
            "offset_mm": round(y, 1),
            "overrun_mm": round(overrun, 1),
            "operation": "sliding",
            "panels": 1,
        },
    )


SYMBOL = Symbol(
    id="door_sliding",
    name="Sliding or pocket door",
    kind="door",
    detect=detect,
    scope="opening",
    priority=5,
    description="A single leaf panel parallel to the wall, offset from the centreline, no arc.",
)


FIXTURES = [
    Fixture(
        name="900 mm sliding leaf overrunning into a pocket",
        width=900,
        wall_thickness=110,
        strokes=[[(-450, 55), (700, 55)]],
        expect=True,
    ),
    Fixture(
        name="1200 mm sliding leaf, flush with the opening",
        width=1200,
        wall_thickness=110,
        strokes=[[(-600, 50), (600, 50)]],
        expect=True,
    ),
    Fixture(
        name="window glazing straddling the centreline",
        width=1500,
        wall_thickness=220,
        strokes=[
            [(-750, 110), (750, 110)],
            [(-750, 0), (750, 0)],
            [(-750, -110), (750, -110)],
        ],
        expect=False,
    ),
    Fixture(
        name="leaf far too short",
        width=1200,
        wall_thickness=110,
        strokes=[[(-600, 50), (-300, 50)]],
        expect=False,
    ),
    Fixture(
        name="perpendicular leaf is a hinged door",
        width=900,
        wall_thickness=110,
        strokes=[[(-450, 0), (-450, 900)]],
        expect=False,
    ),
    Fixture(name="empty opening", width=900, strokes=[], expect=False),
]
