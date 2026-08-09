"""Fire shutter: a roller shutter on a fire layer.

Geometrically a fire shutter and a goods shutter are the same drawing. The
difference is recorded in the CAD layer, not the geometry -- `A-FIRE`, `FS`,
`PCCC` -- and that is genuine information the exporter gave us, so this symbol
reads it.

Without such a layer the same geometry is reported as `door_roller`, which is
the honest answer: the drawing did not say.
"""

from __future__ import annotations

from . import Fixture, Match, OpeningContext, Symbol
from .door_roller import detect as roller_detect

FIRE_LAYER_HINTS = (
    "fire", "-fs", "fs-", "pccc", "chong chay", "chongchay", "smoke", "brand", "rf-",
)


def _fire_layer(ctx: OpeningContext) -> str | None:
    for layer in ctx.layers:
        if not layer:
            continue
        low = layer.lower()
        if any(h in low for h in FIRE_LAYER_HINTS):
            return layer
    return None


def detect(ctx: OpeningContext) -> Match | None:
    layer = _fire_layer(ctx)
    if layer is None:
        return None
    shutter = roller_detect(ctx)
    if shutter is None:
        return None
    meta = dict(shutter.meta)
    meta.update({"operation": "fire_shutter", "fire_layer": layer, "rated": True})
    return Match(kind="door", confidence=min(0.97, shutter.confidence + 0.03), meta=meta)


SYMBOL = Symbol(
    id="door_fire_shutter",
    name="Fire shutter",
    kind="door",
    detect=detect,
    scope="opening",
    priority=50,
    description="Roller shutter geometry drawn on a fire-rated layer.",
)


def _corrugation(width: float, teeth: int, amp: float = 45.0):
    step = width / teeth
    return [(-width / 2.0 + step * i, amp if i % 2 else -amp) for i in range(teeth + 1)]


_STROKES = [_corrugation(3000, 20)]

FIXTURES = [
    Fixture(
        name="corrugated shutter on an A-FIRE layer",
        width=3000,
        wall_thickness=200,
        strokes=_STROKES,
        layers=["A-FIRE-SHUT"],
        expect=True,
    ),
    Fixture(
        name="a Vietnamese PCCC layer",
        width=3000,
        wall_thickness=200,
        strokes=_STROKES,
        layers=["E-PCCC-CUA"],
        expect=True,
    ),
    Fixture(
        name="the same shutter on an ordinary layer is not rated",
        width=3000,
        wall_thickness=200,
        strokes=_STROKES,
        layers=["A-SHUT"],
        expect=False,
    ),
    Fixture(
        name="a fire layer with no shutter drawn on it",
        width=3000,
        wall_thickness=200,
        strokes=[],
        layers=["A-FIRE-SHUT"],
        expect=False,
    ),
    Fixture(
        name="a swing door on a fire layer is a fire door, not a shutter",
        width=900,
        wall_thickness=110,
        strokes=[[(-450, 0), (-450, 900)]],
        layers=["A-FIRE"],
        expect=False,
    ),
]
