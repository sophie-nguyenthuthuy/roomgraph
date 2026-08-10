"""Revision cloud: a scalloped outline marking what changed.

Geometrically identical to `planting` -- both are ragged closed blobs -- and
the two are told apart by where they live rather than what they look like.
Planting is a room feature, on a landscape layer. A revision cloud is a
drawing-management mark, on a revision layer, and it is only claimed when the
drawing says so.

Without the layer it is left to `planting`, which is the better of the two
wrong answers: a tree in the wrong place is a smaller error than a change
nobody made.
"""

from __future__ import annotations

import math
import re

from ..geom import polygon_area
from . import Fixture, Match, PlanContext, Symbol, compactness, fold_text

LAYER_HINTS = ("rev", "cloud", "delta", "sua doi", "thay doi")
TAG = r"\b(rev(?:ision)?\s*\d+|rev\s*[a-z]\b|sua\s*doi)\b"
CLOUD_AREA = (0.5, 400.0)          # m2 on the drawing, at plan scale
COMPACTNESS_RANGE = (0.25, 0.86)
MIN_POINTS = 12


def detect(ctx: PlanContext) -> Match | None:
    tagged = None
    for t in ctx.texts:
        if re.search(TAG, fold_text(t.text)):
            tagged = t.text.strip()
            break

    clouds: list[float] = []
    layers: set[str] = set()
    for index, loop in enumerate(ctx.strokes):
        layer = ctx.layer_of(index)
        on_rev = bool(layer and any(h in fold_text(layer) for h in LAYER_HINTS))
        if not on_rev:
            continue
        if len(loop) < MIN_POINTS:
            continue
        area = abs(polygon_area(loop)) / 1e6
        if not (CLOUD_AREA[0] <= area <= CLOUD_AREA[1]):
            continue
        if not (COMPACTNESS_RANGE[0] <= compactness(loop) <= COMPACTNESS_RANGE[1]):
            continue
        clouds.append(area)
        layers.add(layer)

    if not clouds:
        return None
    conf = 0.70 + 0.08 * min(2, len(clouds) - 1) + (0.10 if tagged else 0.0)
    return Match(
        kind="revision",
        confidence=min(0.90, conf),
        meta={
            "clouds": len(clouds),
            "area_m2": round(sum(clouds), 2),
            "layers": sorted(layers),
            "tag": tagged,
        },
    )


SYMBOL = Symbol(
    id="revision_cloud",
    name="Revision cloud",
    kind="revision",
    detect=detect,
    scope="plan",
    priority=10,
    description="A scalloped outline on a revision layer, marking a change.",
)


def _blob(centre, radius, lobes=11, depth=0.2, steps=96):
    return [
        (
            centre[0] + radius * (1 + depth * math.cos(lobes * 2 * math.pi * i / steps))
            * math.cos(2 * math.pi * i / steps),
            centre[1] + radius * (1 + depth * math.cos(lobes * 2 * math.pi * i / steps))
            * math.sin(2 * math.pi * i / steps),
        )
        for i in range(steps + 1)
    ]


FIXTURES = [
    Fixture(
        name="a cloud on a revision layer, tagged REV 3",
        scope="plan",
        strokes=[_blob((0.0, 0.0), 2500.0)],
        layers=["A-REVC"],
        placed_texts=[("REV 3", (2600.0, 2600.0))],
        expect=True,
    ),
    Fixture(
        name="an untagged cloud on a revision layer",
        scope="plan",
        strokes=[_blob((0.0, 0.0), 2500.0)],
        layers=["X-REV-CLOUD"],
        expect=True,
    ),
    Fixture(
        name="the same blob on a planting layer belongs to planting",
        scope="plan",
        strokes=[_blob((0.0, 0.0), 2500.0)],
        layers=["L-PLNT-TREE"],
        expect=False,
    ),
    Fixture(
        name="a smooth circle on a revision layer is not a cloud",
        scope="plan",
        strokes=[
            [
                (2500.0 * math.cos(2 * math.pi * i / 48), 2500.0 * math.sin(2 * math.pi * i / 48))
                for i in range(49)
            ]
        ],
        layers=["A-REVC"],
        expect=False,
    ),
    Fixture(
        name="an empty drawing",
        scope="plan",
        strokes=[],
        expect=False,
    ),
]
