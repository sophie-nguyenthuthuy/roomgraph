"""Loading dock: levellers and bumpers at a goods entrance.

Label-driven, and worth being blunt about why. A dock leveller is a 2 by 2
metre plate against an external wall, which is indistinguishable from a rug, a
plinth or a hatch. What identifies a dock is that the drawing says so -- the
room is named as one, or the plates sit on a dock layer.

Given that, the geometry then confirms it: two or more matching plates in a
row, which is how docks are set out.
"""

from __future__ import annotations

import statistics

from ..geom import Pt, oriented_extent, polygon_area
from . import Fixture, Match, RoomContext, Symbol, fold_text

LAYER_HINTS = ("dock", "load", "goods", "bocxep", "boc xep", "hang hoa")
TEXT_HINTS = r"\b(loading|dock|goods\s*in|boc\s*xep|hang\s*hoa|leveller|leveler)\b"
PLATE_LONG = (1600.0, 3600.0)
PLATE_SHORT = (1400.0, 3200.0)
MAX_SIZE_SPREAD = 0.12
PITCH = (2500.0, 9000.0)


def detect(ctx: RoomContext) -> Match | None:
    labelled = ctx.text_matches(TEXT_HINTS)
    on_dock_layer = any(
        layer and any(h in fold_text(layer) for h in LAYER_HINTS) for layer in ctx.layers
    )
    if not (labelled or on_dock_layer):
        return None

    plates: list[tuple[Pt, float]] = []
    for loop in ctx.loops():
        if abs(polygon_area(loop)) / 1e6 < 2.0:
            continue
        long_side, short_side = oriented_extent(loop)
        if not (PLATE_LONG[0] <= long_side <= PLATE_LONG[1]):
            continue
        if not (PLATE_SHORT[0] <= short_side <= PLATE_SHORT[1]):
            continue
        centre = Pt(
            sum(p.x for p in loop) / len(loop), sum(p.y for p in loop) / len(loop)
        )
        plates.append((centre, long_side))
    if len(plates) < 2:
        return None

    sizes = [s for _, s in plates]
    if statistics.pstdev(sizes) / statistics.fmean(sizes) > MAX_SIZE_SPREAD:
        return None

    pitch = 0.0
    for axis in (Pt(1.0, 0.0), Pt(0.0, 1.0)):
        positions = sorted(c.dot(axis) for c, _ in plates)
        gaps = [b - a for a, b in zip(positions, positions[1:], strict=False) if b - a > 1.0]
        if not gaps:
            continue
        mean = statistics.fmean(gaps)
        if PITCH[0] <= mean <= PITCH[1]:
            pitch = mean
            break
    if pitch <= 0:
        return None

    conf = 0.68 + 0.08 * min(2, len(plates) - 2)
    conf += 0.10 if on_dock_layer else 0.0
    conf += 0.06 if labelled else 0.0
    return Match(
        kind="loading_dock",
        confidence=min(0.92, conf),
        meta={
            "docks": len(plates),
            "plate_mm": round(statistics.median(sizes), 1),
            "pitch_mm": round(pitch, 1),
            "label": (labelled or "").strip() or None,
        },
    )


SYMBOL = Symbol(
    id="loading_dock",
    name="Loading dock",
    kind="loading_dock",
    detect=detect,
    scope="room",
    priority=12,
    description="Matching leveller plates in a row, in a room the drawing calls a dock.",
)


_YARD = [(0, 0), (20000, 0), (20000, 9000), (0, 9000)]


def _plate(x, y, w=2400, h=2000):
    return [(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)]


FIXTURES = [
    Fixture(
        name="three levellers in a room named as loading",
        polygon=_YARD,
        texts=["LOADING DOCK"],
        strokes=[_plate(1000 + 4000 * i, 500) for i in range(3)],
        expect=True,
    ),
    Fixture(
        name="two plates on a dock layer",
        polygon=_YARD,
        strokes=[_plate(1000, 500), _plate(5000, 500)],
        layers=["A-DOCK", "A-DOCK"],
        expect=True,
    ),
    Fixture(
        name="the same plates with nothing saying dock",
        polygon=_YARD,
        strokes=[_plate(1000, 500), _plate(5000, 500)],
        layers=["A-FURN", "A-FURN"],
        expect=False,
    ),
    Fixture(
        name="a dock label with a single plate",
        polygon=_YARD,
        texts=["LOADING DOCK"],
        strokes=[_plate(1000, 500)],
        expect=False,
    ),
    Fixture(
        name="an empty yard",
        polygon=_YARD,
        texts=["LOADING DOCK"],
        strokes=[],
        expect=False,
    ),
]
