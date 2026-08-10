"""Planting: trees and shrubs, drawn as scalloped blobs.

The measurable fact about a plant symbol is that its outline is *ragged*. A
tree is a circle drawn with a lobed or cloud edge, so its perimeter is far
longer than a smooth circle enclosing the same area.

That is also what keeps it clear of a wheelchair turning circle, which is the
same size and perfectly round. Compactness -- 4*pi*area over perimeter squared
-- is 1.0 for a circle and well below it for a blob, and the gap between the
two is wide enough to sit a threshold in.
"""

from __future__ import annotations

import math

from ..geom import polygon_area
from . import Fixture, Match, RoomContext, Symbol, compactness, fold_text

LAYER_HINTS = ("plnt", "plant", "land", "tree", "cay", "vuon", "green")
CANOPY_AREA = (0.25, 30.0)          # m2
COMPACTNESS_RANGE = (0.30, 0.86)    # blobby, but still roughly round
MIN_POINTS = 10


def detect(ctx: RoomContext) -> Match | None:
    canopies: list[float] = []
    layered = 0
    for index, loop in enumerate(ctx.loops()):
        if len(loop) < MIN_POINTS:
            continue
        area = abs(polygon_area(loop)) / 1e6
        if not (CANOPY_AREA[0] <= area <= CANOPY_AREA[1]):
            continue
        shape = compactness(loop)
        if not (COMPACTNESS_RANGE[0] <= shape <= COMPACTNESS_RANGE[1]):
            continue
        canopies.append(area)
        layer = ctx.layer_of(index)
        if layer and any(h in fold_text(layer) for h in LAYER_HINTS):
            layered += 1

    if not canopies:
        return None
    conf = 0.62 + 0.08 * min(2, len(canopies) - 1) + (0.14 if layered else 0.0)
    return Match(
        kind="planting",
        confidence=min(0.90, conf),
        meta={
            "canopies": len(canopies),
            "canopy_area_m2": round(sum(canopies), 2),
            "on_planting_layer": layered,
        },
    )


SYMBOL = Symbol(
    id="planting",
    name="Planting",
    kind="planting",
    detect=detect,
    scope="room",
    priority=10,
    description="Scalloped canopy outlines: ragged where a turning circle is smooth.",
)


_COURTYARD = [(0, 0), (8000, 0), (8000, 8000), (0, 8000)]


def _blob(centre, radius, lobes=9, depth=0.22, steps=96):
    return [
        (
            centre[0] + radius * (1 + depth * math.cos(lobes * 2 * math.pi * i / steps))
            * math.cos(2 * math.pi * i / steps),
            centre[1] + radius * (1 + depth * math.cos(lobes * 2 * math.pi * i / steps))
            * math.sin(2 * math.pi * i / steps),
        )
        for i in range(steps + 1)
    ]


def _circle(centre, radius, steps=48):
    return [
        (centre[0] + radius * math.cos(2 * math.pi * i / steps),
         centre[1] + radius * math.sin(2 * math.pi * i / steps))
        for i in range(steps + 1)
    ]


FIXTURES = [
    Fixture(
        name="a scalloped tree canopy on a planting layer",
        polygon=_COURTYARD,
        strokes=[_blob((3000, 3000), 1500)],
        layers=["L-PLNT-TREE"],
        expect=True,
    ),
    Fixture(
        name="three shrubs, unlayered",
        polygon=_COURTYARD,
        strokes=[_blob((1500, 1500), 700), _blob((4000, 1500), 700), _blob((6500, 1500), 700)],
        expect=True,
    ),
    Fixture(
        name="a wheelchair turning circle is smooth, not scalloped",
        polygon=_COURTYARD,
        strokes=[_circle((3000, 3000), 750)],
        expect=False,
    ),
    Fixture(
        name="a plain square planter outline",
        polygon=_COURTYARD,
        strokes=[[(1000, 1000), (2500, 1000), (2500, 2500), (1000, 2500), (1000, 1000)]],
        expect=False,
    ),
    Fixture(
        name="an empty courtyard",
        polygon=_COURTYARD,
        strokes=[],
        expect=False,
    ),
]
