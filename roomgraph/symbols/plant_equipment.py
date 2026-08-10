"""Industrial plant: air handling units, chillers, tanks, switchgear.

There is no shape to look for. Plant is whatever the manufacturer's footprint
happens to be, and a 2 by 3 metre rectangle in a plant room is an AHU while the
same rectangle in an office is a meeting table. So this symbol does not pretend
to read geometry: it reads the layer the drafter used, the label they wrote, or
the fact that the room is a plant room.

That makes it the most drawing-dependent symbol in the library, and the least
willing to guess. Strip the layers and labels from a plan and it finds nothing.
"""

from __future__ import annotations

from ..geom import oriented_extent, polygon_area
from . import Fixture, Match, RoomContext, Symbol, fold_text

LAYER_HINTS = (
    "eqpm", "mech", "hvac", "-m-", "m-", "elec", "swbd", "plant", "ahu",
    "chiller", "boiler", "pump", "co dien", "may",
)
TEXT_HINTS = r"\b(ahu|fcu|chiller|boiler|pump|tank|switch\s*board|swbd|generator|genset|may\s*lanh)\b"
FOOTPRINT_AREA = (0.5, 40.0)   # m2
MAX_ASPECT = 6.0


def _plant_layer(ctx: RoomContext, index: int) -> str | None:
    layer = ctx.layer_of(index)
    if not layer:
        return None
    low = fold_text(layer)
    return layer if any(h in low for h in LAYER_HINTS) else None


def detect(ctx: RoomContext) -> Match | None:
    labelled = ctx.text_matches(TEXT_HINTS)
    in_a_plant_room = ctx.category == "technical"

    items: list[float] = []
    layers: set[str] = set()
    for index, loop in enumerate(ctx.strokes):
        if len(loop) < 4:
            continue
        layer = _plant_layer(ctx, index)
        if layer is None and not (labelled or in_a_plant_room):
            continue
        area = abs(polygon_area(loop)) / 1e6
        if not (FOOTPRINT_AREA[0] <= area <= FOOTPRINT_AREA[1]):
            continue
        long_side, short_side = oriented_extent(loop)
        if short_side <= 0 or long_side / short_side > MAX_ASPECT:
            continue
        items.append(area)
        if layer:
            layers.add(layer)

    if not items:
        return None
    conf = 0.60
    conf += 0.14 if layers else 0.0
    conf += 0.08 if labelled else 0.0
    conf += 0.06 if in_a_plant_room else 0.0
    conf += 0.05 * min(2, len(items) - 1)
    return Match(
        kind="plant",
        confidence=min(0.90, conf),
        meta={
            "items": len(items),
            "footprint_m2": round(sum(items), 2),
            "layers": sorted(layers) or None,
            "label": (labelled or "").strip() or None,
        },
    )


SYMBOL = Symbol(
    id="plant_equipment",
    name="Industrial plant",
    kind="plant",
    detect=detect,
    scope="room",
    priority=8,
    description="Equipment footprints on a services layer, labelled, or in a plant room.",
)


_PLANT = [(0, 0), (8000, 0), (8000, 6000), (0, 6000)]
_OFFICE = [(0, 0), (8000, 0), (8000, 6000), (0, 6000)]


def _box(x, y, w, h):
    return [(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)]


FIXTURES = [
    Fixture(
        name="two units on a mechanical equipment layer",
        polygon=_PLANT,
        strokes=[_box(300, 300, 2400, 1600), _box(3200, 300, 1800, 1600)],
        layers=["M-EQPM-AHU", "M-EQPM-AHU"],
        expect=True,
    ),
    Fixture(
        name="an unlayered footprint beside an AHU label",
        polygon=_PLANT,
        texts=["AHU-01"],
        strokes=[_box(300, 300, 2400, 1600)],
        expect=True,
    ),
    Fixture(
        name="a footprint in a room named as plant",
        polygon=_PLANT,
        category="technical",
        strokes=[_box(300, 300, 2400, 1600)],
        expect=True,
    ),
    Fixture(
        name="the same rectangle in an unnamed room is a table",
        polygon=_OFFICE,
        strokes=[_box(300, 300, 2400, 1600)],
        expect=False,
    ),
    Fixture(
        name="a plant layer carrying the room outline",
        polygon=_PLANT,
        category="technical",
        strokes=[_box(100, 100, 7800, 5800)],
        expect=False,
    ),
    Fixture(
        name="an empty plant room",
        polygon=_PLANT,
        category="technical",
        strokes=[],
        expect=False,
    ),
]
