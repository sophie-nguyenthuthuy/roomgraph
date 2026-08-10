"""Escape routes and travel distances.

Plan-scope, because a route is not in a room -- it starts in one, runs through
corridors and leaves by an exit. Only the whole drawing can see it.

It is drawn as an open polyline on an escape layer, usually with the distance
written beside it. Both are recorded, and where a distance is stated it is
compared against the measured run: a route annotated 25 m that measures 31 m is
worth knowing about, and it is the same cross-check the room areas get.
"""

from __future__ import annotations

import re

from ..geom import dist
from . import Fixture, Match, PlanContext, Symbol, fold_text

LAYER_HINTS = ("escape", "egress", "fire", "exit", "thoat hiem", "thoat nan", "evac")
DISTANCE = r"(\d{1,3}(?:[.,]\d)?)\s*m\b"
ROUTE_WORDS = r"\b(travel\s*dist\w*|escape|egress|exit\s*route|thoat\s*hiem|thoat\s*nan)\b"
MIN_ROUTE = 3000.0
TOLERANCE_PCT = 10.0


def _polyline_length(pts) -> float:
    return sum(dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def detect(ctx: PlanContext) -> Match | None:
    routes: list[float] = []
    layers: set[str] = set()
    for index, pts in enumerate(ctx.strokes):
        layer = ctx.layer_of(index)
        if not layer or not any(h in fold_text(layer) for h in LAYER_HINTS):
            continue
        if len(pts) < 2 or dist(pts[0], pts[-1]) <= 80.0:
            continue  # a closed outline is equipment, not a route
        length = _polyline_length(pts)
        if length < MIN_ROUTE:
            continue
        routes.append(length)
        layers.add(layer)
    if not routes:
        return None

    stated: float | None = None
    label: str | None = None
    for t in ctx.texts:
        folded = fold_text(t.text)
        if not re.search(ROUTE_WORDS, folded):
            continue
        m = re.search(DISTANCE, folded)
        if m:
            stated = float(m.group(1).replace(",", "."))
            label = t.text.strip()
            break

    longest = max(routes)
    delta = None
    if stated:
        delta = round(100.0 * (longest / 1000.0 - stated) / stated, 2)

    conf = 0.72 + 0.10 * min(2, len(routes) - 1) + (0.10 if stated else 0.0)
    return Match(
        kind="escape_route",
        confidence=min(0.92, conf),
        meta={
            "routes": len(routes),
            "longest_m": round(longest / 1000.0, 2),
            "stated_m": stated,
            "delta_pct": delta,
            "agrees": None if delta is None else abs(delta) <= TOLERANCE_PCT,
            "layers": sorted(layers),
            "label": label,
        },
    )


SYMBOL = Symbol(
    id="escape_route",
    name="Escape route",
    kind="escape_route",
    detect=detect,
    scope="plan",
    priority=10,
    description="Open polylines on an escape layer, measured against any stated distance.",
)


_ROUTE = [[(1000.0, 1000.0), (1000.0, 9000.0), (12000.0, 9000.0), (12000.0, 11000.0)]]

FIXTURES = [
    Fixture(
        name="a 21 m route annotated as 21 m",
        scope="plan",
        strokes=_ROUTE,
        layers=["A-FIRE-ESCP"],
        placed_texts=[("TRAVEL DISTANCE 21m", (6000.0, 9500.0))],
        expect=True,
    ),
    Fixture(
        name="a route with no annotation",
        scope="plan",
        strokes=_ROUTE,
        layers=["A-EGRESS"],
        expect=True,
    ),
    Fixture(
        name="the same polyline on an ordinary layer",
        scope="plan",
        strokes=_ROUTE,
        layers=["A-ANNO"],
        expect=False,
    ),
    Fixture(
        name="a closed outline on a fire layer is equipment",
        scope="plan",
        strokes=[[(0.0, 0.0), (800.0, 0.0), (800.0, 250.0), (0.0, 250.0), (0.0, 0.0)]],
        layers=["A-FIRE-EQPM"],
        expect=False,
    ),
    Fixture(
        name="an empty drawing",
        scope="plan",
        strokes=[],
        expect=False,
    ),
]
