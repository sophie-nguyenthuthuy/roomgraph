"""Kitchen extract canopy: a hood over the cooking line.

Drawn as a large rectangle above the equipment it serves, on a ventilation
layer. Its proportions are the giveaway -- a canopy is deep, 1000 to 2500,
where the units beneath it are 600 -- and that depth is precisely why it cannot
be confused with the run it sits over.

Away from a ventilation layer or a kitchen it is not claimed: at that point it
is a rectangle, and a rectangle of that size is a table.
"""

from __future__ import annotations

from ..geom import oriented_extent, polygon_area
from . import Fixture, Match, RoomContext, Symbol, fold_text

LAYER_HINTS = ("extr", "kef", "vent", "hvac", "mech", "canopy", "hut mui", "chup hut", "-m-")
TEXT_HINTS = r"\b(canopy|extract|hood|kef|chup\s*hut|hut\s*mui)\b"
CANOPY_LONG = (1500.0, 7000.0)
CANOPY_SHORT = (1000.0, 2500.0)
MIN_AREA = 1.5   # m2


def detect(ctx: RoomContext) -> Match | None:
    labelled = ctx.text_matches(TEXT_HINTS)
    in_a_kitchen = ctx.category == "kitchen"

    best: tuple[float, float, str | None] | None = None
    for index, loop in ctx.loop_items():
        layer = ctx.layer_of(index)
        on_vent = bool(layer and any(h in fold_text(layer) for h in LAYER_HINTS))
        if not (on_vent or labelled or in_a_kitchen):
            continue
        if abs(polygon_area(loop)) / 1e6 < MIN_AREA:
            continue
        long_side, short_side = oriented_extent(loop)
        if not (CANOPY_LONG[0] <= long_side <= CANOPY_LONG[1]):
            continue
        if not (CANOPY_SHORT[0] <= short_side <= CANOPY_SHORT[1]):
            continue
        if best is None or long_side > best[0]:
            best = (long_side, short_side, layer if on_vent else None)
    if best is None:
        return None

    long_side, short_side, layer = best
    conf = 0.62 + (0.14 if layer else 0.0) + (0.10 if labelled else 0.0)
    conf += 0.08 if in_a_kitchen else 0.0
    return Match(
        kind="extract_canopy",
        confidence=min(0.92, conf),
        meta={
            "canopy_mm": [round(long_side, 1), round(short_side, 1)],
            "layer": layer,
            "label": (labelled or "").strip() or None,
        },
    )


SYMBOL = Symbol(
    id="extract_canopy",
    name="Kitchen extract canopy",
    kind="extract_canopy",
    detect=detect,
    scope="room",
    priority=14,
    description="A deep hood outline over a cooking line, on a ventilation layer.",
)


_KITCHEN = [(0, 0), (8000, 0), (8000, 6000), (0, 6000)]


def _box(x, y, w, h):
    return [(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)]


FIXTURES = [
    Fixture(
        name="a 3 m canopy on an extract layer",
        polygon=_KITCHEN,
        strokes=[_box(1000, 1000, 3000, 1400)],
        layers=["M-EXTR-KEF"],
        expect=True,
    ),
    Fixture(
        name="a canopy in a room named as a kitchen",
        polygon=_KITCHEN,
        category="kitchen",
        strokes=[_box(1000, 1000, 3000, 1400)],
        expect=True,
    ),
    Fixture(
        name="the same rectangle in an unnamed room is a table",
        polygon=_KITCHEN,
        strokes=[_box(1000, 1000, 3000, 1400)],
        layers=["A-FURN"],
        expect=False,
    ),
    Fixture(
        name="600 deep units are the run, not the canopy over it",
        polygon=_KITCHEN,
        category="kitchen",
        strokes=[_box(1000, 1000, 3000, 600)],
        expect=False,
    ),
    Fixture(
        name="an empty kitchen",
        polygon=_KITCHEN,
        category="kitchen",
        strokes=[],
        expect=False,
    ),
]
