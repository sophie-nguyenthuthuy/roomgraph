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
    layers: list[str | None] = field(default_factory=list)
    _arcs: list[Arc] | None = None

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
    """Context for room-scope symbols (stairs, fittings)."""

    polygon: list[Pt]
    strokes: list[list[Pt]] = field(default_factory=list)
    area_m2: float = 0.0
    layers: list[str | None] = field(default_factory=list)

    def straight_strokes(self, min_length: float = 1.0) -> list[Seg]:
        out: list[Seg] = []
        for pts in self.strokes:
            for i in range(len(pts) - 1):
                if dist(pts[i], pts[i + 1]) >= min_length:
                    out.append(Seg(pts[i], pts[i + 1]))
        return out


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
    polygon: Sequence[Local] | None = None  # room-scope symbols only
    min_confidence: float = 0.3

    def context(self) -> OpeningContext | RoomContext:
        strokes = [[Pt(float(x), float(y)) for x, y in s] for s in self.strokes]
        if self.polygon is not None:
            ring = [Pt(float(x), float(y)) for x, y in self.polygon]
            return RoomContext(
                polygon=ring, strokes=strokes, area_m2=abs(polygon_area(ring)) / 1e6
            )
        return OpeningContext(
            width=self.width, wall_thickness=self.wall_thickness, strokes=strokes
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
