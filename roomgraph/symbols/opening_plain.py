"""Cased opening: a hole in a wall with no door and no glazing.

Deliberately the weakest detector in the library. It fires whenever a gap has
no symbol drawn in it, at a confidence low enough that any real symbol wins.
Its job is to make sure an unrecognised gap still reaches the room graph as a
connection rather than vanishing.
"""

from __future__ import annotations

from . import Fixture, Match, OpeningContext, Symbol, along_wall, coverage_of

MAX_PLAIN_WIDTH = 3000.0


def detect(ctx: OpeningContext) -> Match | None:
    # The tolerance matters: widths come from a measured scale, so an opening
    # drawn at exactly the limit lands either side of it by a rounding error.
    if not (0 < ctx.width <= MAX_PLAIN_WIDTH + 1.0):
        return None
    if ctx.arcs(min_span_deg=40.0):
        return None

    lo, hi = -ctx.width / 2.0, ctx.width / 2.0
    depth = max(ctx.wall_thickness * 1.6, 60.0)
    for s in ctx.straight_strokes(min_length=0.3 * ctx.width):
        if not along_wall(s):
            continue
        if abs((s.a.y + s.b.y) / 2.0) > depth:
            continue
        if coverage_of([s], lo, hi) >= 0.5:
            return None  # something is drawn in the gap; let its symbol claim it

    # Wide gaps between rooms read as deliberate cased openings; narrow ones
    # are more often a drafting slip, so say so with less confidence.
    conf = 0.30 if ctx.width >= 700.0 else 0.20
    return Match(
        kind="opening",
        confidence=conf,
        meta={"clear_width_mm": round(ctx.width, 1), "reason": "gap with no symbol drawn"},
    )


SYMBOL = Symbol(
    id="opening_plain",
    name="Cased opening (no door)",
    kind="opening",
    detect=detect,
    scope="opening",
    priority=-10,
    description="A wall gap containing no arc and no spanning line.",
)


FIXTURES = [
    Fixture(name="1000 mm empty gap", width=1000, strokes=[], expect=True, min_confidence=0.25),
    Fixture(
        name="gap with unrelated furniture nearby",
        width=1000,
        strokes=[[(200, 900), (900, 900)]],
        expect=True,
        min_confidence=0.25,
    ),
    Fixture(
        name="door swing claims the gap",
        width=900,
        strokes=[[(-450, 0), (-450, 900)], [(-450, 0), (450, 0)]],
        expect=False,
    ),
    Fixture(
        name="glazing claims the gap",
        width=1500,
        wall_thickness=220,
        strokes=[[(-750, 110), (750, 110)], [(-750, -110), (750, -110)]],
        expect=False,
    ),
]
