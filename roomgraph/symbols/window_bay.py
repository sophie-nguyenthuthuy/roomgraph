"""Bay window: a glazed outline that projects out through the opening.

Unlike a flat window, a bay is not lines *inside* the wall -- it is a chain of
straight facets that leaves one jamb, travels out beyond the wall face, and
comes back to the other jamb. Box, canted and bow bays differ only in how many
facets and at what angles, so one detector covers all three.

Finding the chain, rather than just noticing geometry beyond the wall, is what
keeps this away from door swings: a swing arc also leaves a jamb and reaches
far out, but it never connects jamb to jamb as a run of long straight facets.
"""

from __future__ import annotations

import math

from ..geom import Pt, angle_of, dist, is_parallel
from . import Fixture, Match, OpeningContext, Symbol, arc_points

MIN_FACET = 150.0        # a bay facet is a real edge, not a flattened curve chord
MAX_FACETS = 8           # box=3, canted=3, bow=5-7
MIN_DEPTH = 250.0        # shallower than this is a sill or a window board
MAX_DEPTH_RATIO = 1.5    # a bay does not project much further than it is wide
JAMB_RATIO = 0.28        # how close a chain end must sit to a jamb
SNAP = 40.0              # endpoint welding, mm


def _facet_segments(ctx: OpeningContext) -> list[tuple[Pt, Pt]]:
    """Long straight edges only. Flattened bezier chords fall below MIN_FACET,
    which is precisely how door swings get excluded before any path search."""
    out: list[tuple[Pt, Pt]] = []
    for pts in ctx.strokes:
        for i in range(len(pts) - 1):
            if dist(pts[i], pts[i + 1]) >= MIN_FACET:
                out.append((pts[i], pts[i + 1]))
    return out


def _chain_across(ctx: OpeningContext) -> list[Pt] | None:
    """A simple path of facets from one jamb to the other, or None."""
    segs = _facet_segments(ctx)
    if not segs:
        return None

    nodes: list[Pt] = []

    def node_id(p: Pt) -> int:
        for i, q in enumerate(nodes):
            if dist(p, q) <= SNAP:
                return i
        nodes.append(p)
        return len(nodes) - 1

    adjacency: dict[int, set[int]] = {}
    for a, b in segs:
        ia, ib = node_id(a), node_id(b)
        if ia == ib:
            continue
        adjacency.setdefault(ia, set()).add(ib)
        adjacency.setdefault(ib, set()).add(ia)

    left, right = ctx.jambs
    tol = max(JAMB_RATIO * ctx.width, SNAP)

    def anchor(target: Pt) -> int:
        """The node nearest a jamb -- not merely one near it.

        On a bow bay the second facet also falls inside the tolerance, and
        accepting it as an endpoint truncates the chain and under-measures the
        glazed run.
        """
        best, best_d = -1, tol
        for i, q in enumerate(nodes):
            d = dist(q, target)
            if d < best_d:
                best, best_d = i, d
        return best

    start, goal = anchor(left), anchor(right)
    if start < 0 or goal < 0 or start == goal:
        return None
    goals = {goal}

    best: list[int] | None = None

    def walk(node: int, path: list[int], seen: set[int]) -> None:
        nonlocal best
        if best is not None:
            return
        if len(path) > MAX_FACETS + 1:
            return
        if node in goals and len(path) >= 3:
            best = list(path)
            return
        for nxt in sorted(adjacency.get(node, ())):
            if nxt in seen:
                continue
            seen.add(nxt)
            path.append(nxt)
            walk(nxt, path, seen)
            path.pop()
            seen.discard(nxt)

    walk(start, [start], {start})
    return [nodes[i] for i in best] if best else None


def _style(chain: list[Pt]) -> str:
    facets = len(chain) - 1
    if facets >= 4:
        return "bow"
    if facets == 2:
        return "triangular"
    middle = chain[1], chain[2]
    if not is_parallel(middle[1] - middle[0], Pt(1.0, 0.0), tol_deg=8.0):
        return "canted"
    return_dir = chain[1] - chain[0]
    angle = abs(math.degrees(angle_of(return_dir)))
    angle = min(angle, 180.0 - angle)
    return "box" if angle > 75.0 else "canted"


def detect(ctx: OpeningContext) -> Match | None:
    if ctx.width <= 0:
        return None
    chain = _chain_across(ctx)
    if chain is None:
        return None

    depth = max(abs(p.y) for p in chain)
    if depth < max(MIN_DEPTH, 1.5 * ctx.wall_thickness):
        return None
    if depth > MAX_DEPTH_RATIO * ctx.width:
        return None

    # The projection must commit to one side of the wall.
    outward = [p.y for p in chain if abs(p.y) > SNAP]
    if not outward or not (all(y > 0 for y in outward) or all(y < 0 for y in outward)):
        return None

    run = sum(dist(chain[i], chain[i + 1]) for i in range(len(chain) - 1))
    if run <= ctx.width * 1.05:
        return None  # a straight line across the opening is not a bay

    facets = len(chain) - 1
    style = _style(chain)

    conf = 0.70
    conf += 0.12 * min(1.0, depth / (0.35 * ctx.width))
    conf += 0.10 * min(1.0, (run / ctx.width - 1.0) / 0.5)
    if facets in (3, 5):
        conf += 0.05
    return Match(
        kind="window",
        confidence=min(0.95, conf),
        meta={
            "style": style,
            "facets": facets,
            "projection_mm": round(depth, 1),
            "sill_width_mm": round(ctx.width, 1),
            "glazed_run_mm": round(run, 1),
        },
    )


SYMBOL = Symbol(
    id="window_bay",
    name="Bay window",
    kind="window",
    detect=detect,
    scope="opening",
    priority=30,
    description="A chain of straight facets projecting out of the wall from jamb to jamb.",
)


FIXTURES = [
    Fixture(
        name="canted bay, 2400 mm wide, 600 mm projection",
        width=2400,
        wall_thickness=220,
        strokes=[[(-1200, 0), (-700, 600), (700, 600), (1200, 0)]],
        expect=True,
    ),
    Fixture(
        name="square box bay, perpendicular returns",
        width=1800,
        wall_thickness=110,
        strokes=[[(-900, 0), (-900, 500), (900, 500), (900, 0)]],
        expect=True,
    ),
    Fixture(
        name="bow bay, five facets",
        width=2000,
        wall_thickness=220,
        strokes=[
            [(-1000, 0), (-800, 300), (-400, 480), (400, 480), (800, 300), (1000, 0)]
        ],
        expect=True,
    ),
    Fixture(
        name="bay projecting the other way, drawn as separate lines",
        width=1800,
        wall_thickness=110,
        strokes=[
            [(-900, 0), (-500, -550)],
            [(-500, -550), (500, -550)],
            [(500, -550), (900, 0)],
        ],
        expect=True,
    ),
    Fixture(
        name="flat window glazing does not project",
        width=1500,
        wall_thickness=220,
        strokes=[
            [(-750, 110), (750, 110)],
            [(-750, 0), (750, 0)],
            [(-750, -110), (750, -110)],
        ],
        expect=False,
    ),
    Fixture(
        name="door swing reaches out but never spans jamb to jamb in facets",
        width=900,
        wall_thickness=110,
        strokes=[
            [(-450, 0), (-450, 900)],
            arc_points((-450, 0), 900, 90, 0),
        ],
        expect=False,
    ),
    Fixture(
        name="150 mm window board is too shallow to be a bay",
        width=1500,
        wall_thickness=110,
        strokes=[[(-750, 0), (-750, 150), (750, 150), (750, 0)]],
        expect=False,
    ),
    Fixture(
        name="niche attached to one jamb only",
        width=1500,
        wall_thickness=110,
        strokes=[[(-750, 0), (-750, 600), (0, 600)]],
        expect=False,
    ),
    Fixture(
        name="a straight line across the opening is not a bay",
        width=1500,
        wall_thickness=110,
        strokes=[[(-750, 0), (750, 0)]],
        expect=False,
    ),
    Fixture(name="empty opening", width=1800, strokes=[], expect=False),
]
