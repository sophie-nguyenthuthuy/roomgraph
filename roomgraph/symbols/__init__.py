"""The symbol library, and the registry that discovers it.

**One symbol is one file in this package.** A symbol file defines exactly two
module-level names:

    SYMBOL   -- a Symbol describing what it detects and how
    FIXTURES -- Fixture cases proving it fires when it should and stays quiet
                when it should not

`tests/test_symbols.py` walks this package and runs every fixture, so adding a
symbol needs no test edits. See docs/SYMBOLS.md.

Detectors work in a **local frame** so they never deal with plan orientation:
the origin sits at the centre of the opening on the wall centreline, +x runs
along the wall, +y is perpendicular. An opening therefore always spans
x in [-width/2, +width/2].
"""

from __future__ import annotations

import importlib
import math
import pkgutil
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field

from ..geom import Pt, Seg, arc_span, dist, fit_circle, is_parallel, polygon_area

Local = tuple[float, float]


@dataclass
class Arc:
    centre: Pt
    radius: float
    span: float
    points: list[Pt]
    residual: float


@dataclass
class OpeningContext:
    """Everything a symbol needs to judge one opening, in the local frame."""

    width: float
    wall_thickness: float
    strokes: list[list[Pt]] = field(default_factory=list)
    wall_length: float = 0.0
    t_mid: float = 0.0
    bridged: bool = False
    layers: list[str | None] = field(default_factory=list)
    _arcs: list[Arc] | None = None

    def flush_end(self, tol: float | None = None) -> int:
        """Which jamb sits at the end of the wall: -1, +1, or 0 for neither.

        An opening reaching the very end of a wall centreline is unusual --
        ordinarily a wall runs past its openings to the next corner.
        """
        if self.wall_length <= 0 or self.width <= 0:
            return 0
        tol = tol if tol is not None else max(60.0, 0.06 * self.width)
        at_start = (self.t_mid - self.width / 2.0) <= tol
        at_end = (self.t_mid + self.width / 2.0) >= self.wall_length - tol
        if at_start == at_end:
            return 0
        return -1 if at_start else 1

    @property
    def jambs(self) -> tuple[Pt, Pt]:
        return (Pt(-self.width / 2.0, 0.0), Pt(self.width / 2.0, 0.0))

    def arcs(self, min_span_deg: float = 40.0, max_residual_ratio: float = 0.06) -> list[Arc]:
        if self._arcs is None:
            found: list[Arc] = []
            for pts in self.strokes:
                if len(pts) < 4:
                    continue
                fit = fit_circle(pts)
                if not fit:
                    continue
                centre, r, resid = fit
                if r < 1e-6 or resid / r > max_residual_ratio:
                    continue
                found.append(Arc(centre, r, arc_span(pts, centre), list(pts), resid))
            self._arcs = found
        return [a for a in self._arcs if math.degrees(a.span) >= min_span_deg]

    def straight_strokes(self, min_length: float = 1.0) -> list[Seg]:
        """Strokes that are (near enough) a single straight run."""
        out: list[Seg] = []
        for pts in self.strokes:
            if len(pts) < 2:
                continue
            chord = dist(pts[0], pts[-1])
            if chord < min_length:
                continue
            path = sum(dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))
            if path <= chord * 1.02:
                out.append(Seg(pts[0], pts[-1]))
        return out


@dataclass
class RoomContext:
    """Context for room-scope symbols (stairs, fittings, plant).

    `layers`, `filled` and `strokes` are parallel lists. `category` and `texts`
    come from the room itself: a ramp is read from its gradient label as much as
    its geometry, and a 700 mm square means different things in a kitchen and a
    shower room.
    """

    polygon: list[Pt]
    strokes: list[list[Pt]] = field(default_factory=list)
    area_m2: float = 0.0
    layers: list[str | None] = field(default_factory=list)
    filled: list[bool] = field(default_factory=list)
    category: str = "unknown"
    texts: list[str] = field(default_factory=list)

    def layer_of(self, index: int) -> str | None:
        return self.layers[index] if index < len(self.layers) else None

    def is_filled(self, index: int) -> bool:
        return self.filled[index] if index < len(self.filled) else False

    def text_matches(self, pattern: str) -> str | None:
        """First room label matching a regular expression, case-insensitively."""
        import re

        for t in self.texts:
            if re.search(pattern, t, re.I):
                return t
        return None

    def straight_strokes(self, min_length: float = 1.0) -> list[Seg]:
        out: list[Seg] = []
        for pts in self.strokes:
            for i in range(len(pts) - 1):
                if dist(pts[i], pts[i + 1]) >= min_length:
                    out.append(Seg(pts[i], pts[i + 1]))
        return out

    def loops(self, tol: float = 80.0) -> list[list[Pt]]:
        """Strokes that close back on themselves: fittings, cars, furniture."""
        return [
            pts for pts in self.strokes
            if len(pts) >= 4 and dist(pts[0], pts[-1]) <= tol
        ]


@dataclass
class Match:
    kind: str
    confidence: float
    meta: dict = field(default_factory=dict)


@dataclass
class Fixture:
    """A self-contained case in the local frame. Coordinates are millimetres."""

    name: str
    strokes: Sequence[Sequence[Local]]
    expect: bool
    width: float = 900.0
    wall_thickness: float = 110.0
    wall_length: float = 0.0
    t_mid: float = 0.0
    bridged: bool = False
    layers: Sequence[str | None] | None = None
    polygon: Sequence[Local] | None = None  # room-scope symbols only
    filled: Sequence[bool] | None = None    # room scope: parallel to strokes
    category: str = "unknown"               # room scope
    texts: Sequence[str] = ()               # room scope
    min_confidence: float = 0.3

    def context(self) -> OpeningContext | RoomContext:
        strokes = [[Pt(float(x), float(y)) for x, y in s] for s in self.strokes]
        if self.polygon is not None:
            ring = [Pt(float(x), float(y)) for x, y in self.polygon]
            return RoomContext(
                polygon=ring,
                strokes=strokes,
                area_m2=abs(polygon_area(ring)) / 1e6,
                layers=list(self.layers or [None] * len(strokes)),
                filled=list(self.filled or [False] * len(strokes)),
                category=self.category,
                texts=list(self.texts),
            )
        return OpeningContext(
            width=self.width,
            wall_thickness=self.wall_thickness,
            strokes=strokes,
            wall_length=self.wall_length,
            t_mid=self.t_mid,
            bridged=self.bridged,
            layers=list(self.layers or [None] * len(strokes)),
        )


@dataclass
class Symbol:
    id: str
    name: str
    kind: str
    detect: Callable[[OpeningContext], Match | None] | Callable[[RoomContext], Match | None]
    scope: str = "opening"  # "opening" | "room"
    description: str = ""
    priority: int = 0

    def __post_init__(self) -> None:
        if self.scope not in ("opening", "room"):
            raise ValueError(f"{self.id}: scope must be 'opening' or 'room'")


# -- helpers for symbol authors ---------------------------------------------
def arc_points(
    centre: Local, radius: float, start_deg: float, end_deg: float, steps: int = 24
) -> list[Local]:
    """Sample an arc -- for writing fixtures that look like real CAD output."""
    cx, cy = centre
    a0, a1 = math.radians(start_deg), math.radians(end_deg)
    return [
        (cx + radius * math.cos(a0 + (a1 - a0) * i / steps),
         cy + radius * math.sin(a0 + (a1 - a0) * i / steps))
        for i in range(steps + 1)
    ]


def along_wall(seg: Seg, tol_deg: float = 8.0) -> bool:
    return is_parallel(seg.vec, Pt(1.0, 0.0), tol_deg=tol_deg)


def span_x(seg: Seg) -> tuple[float, float]:
    return (min(seg.a.x, seg.b.x), max(seg.a.x, seg.b.x))


def coverage_of(segs: Iterable[Seg], lo: float, hi: float) -> float:
    """Fraction of [lo, hi] covered by the x-projection of `segs`."""
    if hi <= lo:
        return 0.0
    iv = []
    for s in segs:
        a, b = span_x(s)
        a, b = max(a, lo), min(b, hi)
        if b > a:
            iv.append((a, b))
    if not iv:
        return 0.0
    iv.sort()
    total, cur_a, cur_b = 0.0, iv[0][0], iv[0][1]
    for a, b in iv[1:]:
        if a > cur_b:
            total += cur_b - cur_a
            cur_a, cur_b = a, b
        else:
            cur_b = max(cur_b, b)
    total += cur_b - cur_a
    return total / (hi - lo)


def facet_chain(
    ctx: OpeningContext,
    min_facet: float = 150.0,
    max_facets: int = 8,
    snap: float = 40.0,
    jamb_ratio: float = 0.28,
) -> list[Pt] | None:
    """A simple path of straight facets running from one jamb to the other.

    Shared by every symbol whose signature is a *shape spanning the opening* --
    bay windows project out and back, folding doors zigzag. Facets shorter than
    `min_facet` are ignored, which is what stops a flattened bezier arc (a door
    swing) from ever forming a path.
    """
    segs: list[tuple[Pt, Pt]] = []
    for pts in ctx.strokes:
        for i in range(len(pts) - 1):
            if dist(pts[i], pts[i + 1]) >= min_facet:
                segs.append((pts[i], pts[i + 1]))
    if not segs:
        return None

    nodes: list[Pt] = []

    def node_id(p: Pt) -> int:
        for i, q in enumerate(nodes):
            if dist(p, q) <= snap:
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
    tol = max(jamb_ratio * ctx.width, snap)

    def anchor(target: Pt) -> int:
        """The node *nearest* a jamb, not merely one near it.

        On a bow bay the second facet also falls inside the tolerance, and
        accepting it as an endpoint truncates the chain.
        """
        best_i, best_d = -1, tol
        for i, q in enumerate(nodes):
            d = dist(q, target)
            if d < best_d:
                best_i, best_d = i, d
        return best_i

    start, goal = anchor(left), anchor(right)
    if start < 0 or goal < 0 or start == goal:
        return None

    found: list[int] | None = None

    def walk(node: int, path: list[int], seen: set[int]) -> None:
        nonlocal found
        if found is not None or len(path) > max_facets + 1:
            return
        if node == goal and len(path) >= 3:
            found = list(path)
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
    return [nodes[i] for i in found] if found else None


# -- registry ----------------------------------------------------------------
_REGISTRY: dict[str, Symbol] = {}
_FIXTURES: dict[str, list[Fixture]] = {}
_LOADED = False


def _load() -> None:
    global _LOADED
    if _LOADED:
        return
    _LOADED = True
    for info in pkgutil.iter_modules(__path__):
        if info.name.startswith("_"):
            continue
        mod = importlib.import_module(f"{__name__}.{info.name}")
        sym = getattr(mod, "SYMBOL", None)
        if sym is None:
            continue
        if not isinstance(sym, Symbol):
            raise TypeError(f"{info.name}: SYMBOL must be a Symbol instance")
        if sym.id in _REGISTRY:
            raise ValueError(f"duplicate symbol id {sym.id!r} in {info.name}")
        _REGISTRY[sym.id] = sym
        _FIXTURES[sym.id] = list(getattr(mod, "FIXTURES", []))


def registry() -> dict[str, Symbol]:
    _load()
    return dict(_REGISTRY)


def fixtures() -> dict[str, list[Fixture]]:
    _load()
    return dict(_FIXTURES)


def symbols_for(scope: str) -> list[Symbol]:
    return sorted(
        (s for s in registry().values() if s.scope == scope),
        key=lambda s: (-s.priority, s.id),
    )


def best_match(ctx: OpeningContext | RoomContext, scope: str) -> tuple[Symbol, Match] | None:
    """Run every symbol of a scope and keep the most confident answer."""
    best: tuple[Symbol, Match] | None = None
    for sym in symbols_for(scope):
        try:
            m = sym.detect(ctx)  # type: ignore[arg-type]
        except Exception:
            continue  # a broken contributed symbol must not sink the run
        if m is None:
            continue
        if best is None or m.confidence > best[1].confidence:
            best = (sym, m)
    return best
