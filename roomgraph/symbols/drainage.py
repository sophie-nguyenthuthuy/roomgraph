"""Drainage: floor gullies and channels.

Layer-driven, because a 150 mm square is nothing on its own. What a drainage
layer gives you is which small marks are gullies, and the fall annotations
beside them -- `1:80`, `FALL` -- which are recorded when present.

A linear channel drain is included: a long thin outline on the same layer,
which is how a shower or kitchen channel is drawn.
"""

from __future__ import annotations

import re

from ..geom import oriented_extent, polygon_area
from . import Fixture, Match, RoomContext, Symbol, fold_text

LAYER_HINTS = ("drai", "-p-", "p-", "plumb", "gully", "sewer", "thoat nuoc", "ga thu")
TEXT_HINTS = r"\b(fd|gully|floor\s*drain|ga\s*thu|thoat\s*san|channel)\b"
FALL = r"\b1\s*[:/]\s*(\d{2,3})\b"

GULLY_SIZE = (80.0, 450.0)
CHANNEL_LONG = (600.0, 6000.0)
CHANNEL_SHORT = (60.0, 300.0)


def _on_drainage_layer(ctx: RoomContext, index: int) -> str | None:
    layer = ctx.layer_of(index)
    if not layer:
        return None
    low = fold_text(layer)
    return layer if any(h in low for h in LAYER_HINTS) else None


def detect(ctx: RoomContext) -> Match | None:
    labelled = ctx.text_matches(TEXT_HINTS)
    gullies = 0
    channels = 0
    layers: set[str] = set()

    for index, loop in enumerate(ctx.strokes):
        if len(loop) < 4:
            continue
        layer = _on_drainage_layer(ctx, index)
        if layer is None and not labelled:
            continue
        if abs(polygon_area(loop)) / 1e6 > 4.0:
            continue
        long_side, short_side = oriented_extent(loop)
        if (
            GULLY_SIZE[0] <= long_side <= GULLY_SIZE[1]
            and GULLY_SIZE[0] <= short_side <= GULLY_SIZE[1]
        ):
            gullies += 1
        elif (
            CHANNEL_LONG[0] <= long_side <= CHANNEL_LONG[1]
            and CHANNEL_SHORT[0] <= short_side <= CHANNEL_SHORT[1]
        ):
            channels += 1
        else:
            continue
        if layer:
            layers.add(layer)

    if gullies + channels == 0:
        return None

    fall = None
    for t in ctx.texts:
        m = re.search(FALL, t)
        if m and 20 <= int(m.group(1)) <= 200:
            fall = f"1:{m.group(1)}"
            break

    conf = 0.66 + (0.12 if layers else 0.0) + (0.06 if labelled else 0.0)
    conf += 0.06 if fall else 0.0
    return Match(
        kind="drainage",
        confidence=min(0.90, conf),
        meta={
            "gullies": gullies,
            "channels": channels,
            "fall": fall,
            "layers": sorted(layers) or None,
        },
    )


SYMBOL = Symbol(
    id="drainage",
    name="Drainage",
    kind="drainage",
    detect=detect,
    scope="room",
    priority=12,
    description="Gullies and channel drains on a drainage layer, with any stated fall.",
)


_PLANT = [(0, 0), (6000, 0), (6000, 4000), (0, 4000)]


def _box(x, y, w, h):
    return [(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)]


FIXTURES = [
    Fixture(
        name="two gullies on a drainage layer with a stated fall",
        polygon=_PLANT,
        texts=["FALL 1:80"],
        strokes=[_box(1000, 1000, 200, 200), _box(4000, 1000, 200, 200)],
        layers=["P-DRAI-FLOR", "P-DRAI-FLOR"],
        expect=True,
    ),
    Fixture(
        name="a linear channel drain",
        polygon=_PLANT,
        strokes=[_box(1000, 1000, 2400, 150)],
        layers=["P-DRAI"],
        expect=True,
    ),
    Fixture(
        name="an unlayered gully beside an FD label",
        polygon=_PLANT,
        texts=["FD"],
        strokes=[_box(1000, 1000, 200, 200)],
        expect=True,
    ),
    Fixture(
        name="the same square on a furniture layer",
        polygon=_PLANT,
        strokes=[_box(1000, 1000, 200, 200)],
        layers=["A-FURN"],
        expect=False,
    ),
    Fixture(
        name="a drainage layer carrying something room-sized",
        polygon=_PLANT,
        strokes=[_box(200, 200, 5000, 3000)],
        layers=["P-DRAI"],
        expect=False,
    ),
    Fixture(
        name="an empty room",
        polygon=_PLANT,
        strokes=[],
        expect=False,
    ),
]
