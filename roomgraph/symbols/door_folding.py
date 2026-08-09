"""Folding door: a concertina of equal leaves zigzagging across the opening.

Bi-fold, accordion and folding partitions all draw the same way in plan -- a
run of equal-length leaves hinged end to end, alternating to either side of the
wall line as they fold.

Two properties do the identifying. The leaves are *equal*, which no bay window
is: a bay's returns are short and its front facet long. And the chain
*alternates*, returning toward the wall line between leaves, where a bay stays
out in its projection the whole way.

A two-leaf bi-fold drawn as a plain V is deliberately not claimed. At two
facets there is nothing left to separate it from a triangular bay window, and a
wrong answer costs more than a missing one.
"""

from __future__ import annotations

import statistics

from ..geom import dist
from . import Fixture, Match, OpeningContext, Symbol, arc_points, facet_chain

MIN_LEAVES = 3
MAX_LEAVES = 8
MAX_LEAF_SPREAD = 0.22   # coefficient of variation across leaf lengths
MIN_FOLD_RATIO = 0.12    # fold depth as a fraction of leaf length
MAX_FOLD_RATIO = 1.10
MIN_SPAN_RATIO = 0.75    # the chain must cross most of the opening


def detect(ctx: OpeningContext) -> Match | None:
    if ctx.width <= 0:
        return None
    chain = facet_chain(
        ctx,
        min_facet=max(110.0, ctx.width / 12.0),
        max_facets=MAX_LEAVES,
    )
    if chain is None or not (MIN_LEAVES <= len(chain) - 1 <= MAX_LEAVES):
        return None

    leaves = [dist(chain[i], chain[i + 1]) for i in range(len(chain) - 1)]
    mean_leaf = statistics.fmean(leaves)
    if mean_leaf <= 0:
        return None
    spread = statistics.pstdev(leaves) / mean_leaf
    if spread > MAX_LEAF_SPREAD:
        return None  # unequal facets: a bay window, not a concertina

    # Leaves must alternate across the wall line and march steadily along it.
    dys = [chain[i + 1].y - chain[i].y for i in range(len(chain) - 1)]
    dxs = [chain[i + 1].x - chain[i].x for i in range(len(chain) - 1)]
    if any(abs(dy) < MIN_FOLD_RATIO * mean_leaf for dy in dys):
        return None
    for a, b in zip(dys, dys[1:], strict=False):
        if a * b >= 0:
            return None
    if not (all(dx > 0 for dx in dxs) or all(dx < 0 for dx in dxs)):
        return None

    fold = max(abs(p.y) for p in chain)
    if not (MIN_FOLD_RATIO * mean_leaf <= fold <= MAX_FOLD_RATIO * mean_leaf):
        return None
    span = abs(chain[-1].x - chain[0].x)
    if span < MIN_SPAN_RATIO * ctx.width:
        return None

    conf = 0.74
    conf += 0.12 * (1.0 - spread / MAX_LEAF_SPREAD)
    conf += 0.06 * min(1.0, (len(leaves) - MIN_LEAVES) / 3.0)
    conf += 0.05 * min(1.0, span / ctx.width)
    return Match(
        kind="door",
        confidence=min(0.95, conf),
        meta={
            "operation": "folding",
            "panels": len(leaves),
            "leaf_width_mm": round(mean_leaf, 1),
            "fold_depth_mm": round(fold, 1),
            "leaf_spread": round(spread, 3),
        },
    )


SYMBOL = Symbol(
    id="door_folding",
    name="Folding or bi-fold door",
    kind="door",
    detect=detect,
    scope="opening",
    priority=25,
    description="Three or more equal leaves zigzagging alternately across the opening.",
)


def _zigzag(width: float, leaves: int, fold: float) -> list[tuple[float, float]]:
    """A concertina of `leaves` equal panels spanning the opening."""
    step = width / leaves
    return [
        (-width / 2.0 + step * i, 0.0 if i % 2 == 0 else fold)
        for i in range(leaves + 1)
    ]


FIXTURES = [
    Fixture(
        name="four-leaf concertina across a 1800 mm opening",
        width=1800,
        wall_thickness=110,
        strokes=[_zigzag(1800, 4, 320)],
        expect=True,
    ),
    Fixture(
        name="six-leaf folding partition",
        width=3000,
        wall_thickness=110,
        strokes=[_zigzag(3000, 6, 400)],
        expect=True,
    ),
    Fixture(
        name="three leaves, folding the other way",
        width=1500,
        wall_thickness=110,
        strokes=[_zigzag(1500, 3, -380)],
        expect=True,
    ),
    Fixture(
        name="leaves drawn as separate lines rather than one polyline",
        width=1800,
        wall_thickness=110,
        strokes=[
            [(-900, 0), (-450, 320)],
            [(-450, 320), (0, 0)],
            [(0, 0), (450, 320)],
            [(450, 320), (900, 0)],
        ],
        expect=True,
    ),
    Fixture(
        name="canted bay window: unequal facets, never returns to the wall",
        width=2400,
        wall_thickness=220,
        strokes=[[(-1200, 0), (-700, 600), (700, 600), (1200, 0)]],
        expect=False,
    ),
    Fixture(
        name="box bay window",
        width=1800,
        wall_thickness=110,
        strokes=[[(-900, 0), (-900, 500), (900, 500), (900, 0)]],
        expect=False,
    ),
    Fixture(
        name="single swing door",
        width=900,
        wall_thickness=110,
        strokes=[
            [(-450, 0), (-450, 900)],
            arc_points((-450, 0), 900, 90, 0),
        ],
        expect=False,
    ),
    Fixture(
        name="flat glazing spanning the opening",
        width=1500,
        wall_thickness=220,
        strokes=[
            [(-750, 110), (750, 110)],
            [(-750, -110), (750, -110)],
        ],
        expect=False,
    ),
    Fixture(
        name="a two-leaf V is not claimed: a triangular bay looks the same",
        width=1200,
        wall_thickness=110,
        strokes=[[(-600, 0), (0, 380), (600, 0)]],
        expect=False,
    ),
    Fixture(name="empty opening", width=1800, strokes=[], expect=False),
]
