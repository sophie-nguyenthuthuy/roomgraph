"""Fire equipment: hydrants, hose reels and dry risers.

Layer-driven, like `door_fire_shutter`, and for the same reason: a hose reel
cabinet and a stationery cupboard are the same 800 by 250 box. What tells them
apart is which layer the drafter put it on, or what they wrote beside it --
`FH`, `PCCC`, `dry riser`. That is real information the exporter handed us.

Strip the layers from a drawing and this finds nothing, which is correct. The
drawing no longer says.
"""

from __future__ import annotations

from ..geom import oriented_extent, polygon_area
from . import Fixture, Match, RoomContext, Symbol, fold_text

LAYER_HINTS = ("fire", "pccc", "-fh", "fh-", "hydrant", "riser", "hose", "chua chay")
TEXT_HINTS = r"\b(fh|fhc|hydrant|hose\s*reel|dry\s*riser|wet\s*riser|pccc|chua\s*chay)\b"

CABINET_LONG = (350.0, 1400.0)
CABINET_SHORT = (120.0, 700.0)
MIN_AREA = 0.02   # m2
MAX_AREA = 0.9


def _fire_layer(ctx: RoomContext, index: int) -> str | None:
    layer = ctx.layer_of(index)
    if not layer:
        return None
    low = fold_text(layer)
    return layer if any(h in low for h in LAYER_HINTS) else None


def detect(ctx: RoomContext) -> Match | None:
    labelled = ctx.text_matches(TEXT_HINTS)
    items: list[tuple[float, float]] = []
    layers: set[str] = set()

    for index, loop in enumerate(ctx.strokes):
        if len(loop) < 4:
            continue
        layer = _fire_layer(ctx, index)
        if layer is None and not labelled:
            continue
        area = abs(polygon_area(loop)) / 1e6
        if not (MIN_AREA <= area <= MAX_AREA):
            continue
        long_side, short_side = oriented_extent(loop)
        if not (CABINET_LONG[0] <= long_side <= CABINET_LONG[1]):
            continue
        if not (CABINET_SHORT[0] <= short_side <= CABINET_SHORT[1]):
            continue
        items.append((long_side, short_side))
        if layer:
            layers.add(layer)

    if not items:
        return None
    conf = 0.72 + (0.10 if layers else 0.0) + (0.08 if labelled else 0.0)
    conf += 0.04 * min(1.0, (len(items) - 1) / 2.0)
    return Match(
        kind="fire_equipment",
        confidence=min(0.92, conf),
        meta={
            "items": len(items),
            "size_mm": [round(items[0][0], 1), round(items[0][1], 1)],
            "layers": sorted(layers) or None,
            "label": (labelled or "").strip() or None,
        },
    )


SYMBOL = Symbol(
    id="fire_equipment",
    name="Fire equipment",
    kind="fire_equipment",
    detect=detect,
    scope="room",
    priority=20,
    description="Cabinet-sized outlines on a fire layer, or beside a fire label.",
)


_LOBBY = [(0, 0), (6000, 0), (6000, 4000), (0, 4000)]


def _box(x, y, w, h):
    return [(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)]


FIXTURES = [
    Fixture(
        name="a hose reel cabinet on an A-FIRE layer",
        polygon=_LOBBY,
        strokes=[_box(200, 200, 800, 250)],
        layers=["A-FIRE-EQPM"],
        expect=True,
    ),
    Fixture(
        name="two cabinets on a Vietnamese PCCC layer",
        polygon=_LOBBY,
        strokes=[_box(200, 200, 800, 250), _box(3000, 200, 800, 250)],
        layers=["E-PCCC-TB", "E-PCCC-TB"],
        expect=True,
    ),
    Fixture(
        name="an unlayered cabinet beside an FH label",
        polygon=_LOBBY,
        texts=["FH"],
        strokes=[_box(200, 200, 800, 250)],
        expect=True,
    ),
    Fixture(
        name="the same box on an ordinary layer says nothing",
        polygon=_LOBBY,
        strokes=[_box(200, 200, 800, 250)],
        layers=["A-FURN"],
        expect=False,
    ),
    Fixture(
        name="a fire layer with a whole wall drawn on it",
        polygon=_LOBBY,
        strokes=[_box(200, 200, 5000, 3000)],
        layers=["A-FIRE-EQPM"],
        expect=False,
    ),
    Fixture(
        name="an empty lobby",
        polygon=_LOBBY,
        strokes=[],
        expect=False,
    ),
]
