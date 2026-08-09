"""Planar geometry primitives.

Everything downstream speaks these types. Coordinates are floats in whatever
unit the caller established (page points before scaling, millimetres after).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

EPS = 1e-9


@dataclass(frozen=True)
class Pt:
    x: float
    y: float

    def __add__(self, o: Pt) -> Pt:
        return Pt(self.x + o.x, self.y + o.y)

    def __sub__(self, o: Pt) -> Pt:
        return Pt(self.x - o.x, self.y - o.y)

    def __mul__(self, k: float) -> Pt:
        return Pt(self.x * k, self.y * k)

    __rmul__ = __mul__

    def dot(self, o: Pt) -> float:
        return self.x * o.x + self.y * o.y

    def cross(self, o: Pt) -> float:
        return self.x * o.y - self.y * o.x

    def norm(self) -> float:
        return math.hypot(self.x, self.y)

    def unit(self) -> Pt:
        n = self.norm()
        return Pt(0.0, 0.0) if n < EPS else Pt(self.x / n, self.y / n)

    def perp(self) -> Pt:
        """Left normal (90 degrees counter-clockwise)."""
        return Pt(-self.y, self.x)

    def rounded(self, nd: int = 4) -> tuple[float, float]:
        return (round(self.x, nd), round(self.y, nd))


@dataclass(frozen=True)
class Seg:
    a: Pt
    b: Pt

    @property
    def vec(self) -> Pt:
        return self.b - self.a

    def length(self) -> float:
        return self.vec.norm()

    def dir(self) -> Pt:
        return self.vec.unit()

    def midpoint(self) -> Pt:
        return Pt((self.a.x + self.b.x) / 2.0, (self.a.y + self.b.y) / 2.0)

    def point_at(self, t: float) -> Pt:
        return Pt(self.a.x + self.vec.x * t, self.a.y + self.vec.y * t)

    def reversed(self) -> Seg:
        return Seg(self.b, self.a)


def dist(p: Pt, q: Pt) -> float:
    return math.hypot(p.x - q.x, p.y - q.y)


def angle_of(v: Pt) -> float:
    return math.atan2(v.y, v.x)


def angle_diff(a: float, b: float) -> float:
    """Smallest signed difference between two angles, in (-pi, pi]."""
    d = (a - b) % (2 * math.pi)
    if d > math.pi:
        d -= 2 * math.pi
    return d


def is_parallel(u: Pt, v: Pt, tol_deg: float = 2.0) -> bool:
    """Parallel *or* antiparallel, within tolerance."""
    au, av = angle_of(u) % math.pi, angle_of(v) % math.pi
    d = abs(au - av)
    d = min(d, math.pi - d)
    return d <= math.radians(tol_deg)


def point_seg_distance(p: Pt, s: Seg) -> float:
    v = s.vec
    ln2 = v.dot(v)
    if ln2 < EPS:
        return dist(p, s.a)
    t = max(0.0, min(1.0, (p - s.a).dot(v) / ln2))
    return dist(p, s.point_at(t))


def project_param(p: Pt, s: Seg) -> float:
    """Parameter t (unclamped) of p projected onto the line through s."""
    v = s.vec
    ln2 = v.dot(v)
    if ln2 < EPS:
        return 0.0
    return (p - s.a).dot(v) / ln2


def seg_intersection(s1: Seg, s2: Seg, tol: float = 1e-7) -> Pt | None:
    """Proper intersection point of two segments, or None.

    Collinear overlap returns None -- collinear pairs are handled by the
    snapping/merging passes instead, where the intent is clearer.
    """
    r, s = s1.vec, s2.vec
    denom = r.cross(s)
    if abs(denom) < tol:
        return None
    qp = s2.a - s1.a
    t = qp.cross(s) / denom
    u = qp.cross(r) / denom
    if -tol <= t <= 1 + tol and -tol <= u <= 1 + tol:
        return s1.point_at(t)
    return None


def polygon_area(pts: Sequence[Pt]) -> float:
    """Signed area; positive when the ring is counter-clockwise."""
    n = len(pts)
    if n < 3:
        return 0.0
    acc = 0.0
    for i in range(n):
        p, q = pts[i], pts[(i + 1) % n]
        acc += p.cross(q)
    return acc / 2.0


def polygon_perimeter(pts: Sequence[Pt]) -> float:
    n = len(pts)
    return sum(dist(pts[i], pts[(i + 1) % n]) for i in range(n))


def polygon_centroid(pts: Sequence[Pt]) -> Pt:
    a = polygon_area(pts)
    if abs(a) < EPS:
        n = max(1, len(pts))
        return Pt(sum(p.x for p in pts) / n, sum(p.y for p in pts) / n)
    cx = cy = 0.0
    n = len(pts)
    for i in range(n):
        p, q = pts[i], pts[(i + 1) % n]
        cr = p.cross(q)
        cx += (p.x + q.x) * cr
        cy += (p.y + q.y) * cr
    return Pt(cx / (6 * a), cy / (6 * a))


def point_in_polygon(p: Pt, pts: Sequence[Pt]) -> bool:
    """Ray casting. Points exactly on the boundary are unspecified."""
    inside = False
    n = len(pts)
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        if (a.y > p.y) != (b.y > p.y):
            xin = a.x + (p.y - a.y) * (b.x - a.x) / (b.y - a.y)
            if xin > p.x:
                inside = not inside
    return inside


def representative_point(pts: Sequence[Pt]) -> Pt:
    """A point guaranteed inside the polygon (centroid may fall outside for L-shapes)."""
    c = polygon_centroid(pts)
    if point_in_polygon(c, pts):
        return c
    ys = sorted({p.y for p in pts})
    for i in range(len(ys) - 1):
        y = (ys[i] + ys[i + 1]) / 2.0
        xs = []
        n = len(pts)
        for j in range(n):
            a, b = pts[j], pts[(j + 1) % n]
            if (a.y > y) != (b.y > y):
                xs.append(a.x + (y - a.y) * (b.x - a.x) / (b.y - a.y))
        xs.sort()
        for k in range(0, len(xs) - 1, 2):
            if xs[k + 1] - xs[k] > EPS:
                return Pt((xs[k] + xs[k + 1]) / 2.0, y)
    return c


def oriented_extent(pts: Sequence[Pt]) -> tuple[float, float]:
    """(long side, short side) of the outline, measured along its own axes.

    Fittings are routinely drawn at an angle, so an axis-aligned box would
    report a 1700 mm bath as something square. The longest edge sets the axis.
    """
    if len(pts) < 2:
        return (0.0, 0.0)
    best_dir, best_len = Pt(1.0, 0.0), 0.0
    n = len(pts)
    for i in range(n):
        v = pts[(i + 1) % n] - pts[i]
        if v.norm() > best_len:
            best_dir, best_len = v.unit(), v.norm()
    nrm = best_dir.perp()
    us = [p.dot(best_dir) for p in pts]
    vs = [p.dot(nrm) for p in pts]
    a, b = max(us) - min(us), max(vs) - min(vs)
    return (max(a, b), min(a, b))


def bbox(pts: Iterable[Pt]) -> tuple[float, float, float, float]:
    xs = [p.x for p in pts]
    ys = [p.y for p in pts]
    if not xs:
        return (0.0, 0.0, 0.0, 0.0)
    return (min(xs), min(ys), max(xs), max(ys))


def offset_polygon(pts: Sequence[Pt], distances: Sequence[float]) -> list[Pt]:
    """Offset each edge inward by its own distance, then re-intersect.

    `distances[i]` applies to the edge from pts[i] to pts[i+1]. Adequate for the
    convex-ish, mostly rectilinear room rings we produce; it does not handle
    self-intersection from over-offsetting, so callers should sanity-check area.
    """
    n = len(pts)
    if n < 3:
        return list(pts)
    ccw = polygon_area(pts) > 0
    lines: list[tuple[Pt, Pt]] = []
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        d = (b - a).unit()
        if d.norm() < EPS:
            lines.append((a, Pt(1.0, 0.0)))
            continue
        # Inward normal: left of travel direction for a CCW ring.
        nrm = d.perp() if ccw else d.perp() * -1.0
        off = distances[i] if i < len(distances) else 0.0
        lines.append((a + nrm * off, d))

    out: list[Pt] = []
    for i in range(n):
        p0, d0 = lines[i - 1]
        p1, d1 = lines[i]
        denom = d0.cross(d1)
        if abs(denom) < 1e-6:
            out.append(p1)
            continue
        t = (p1 - p0).cross(d1) / denom
        out.append(p0 + d0 * t)
    return out


def dedupe_points(pts: Sequence[Pt], tol: float) -> list[Pt]:
    out: list[Pt] = []
    for p in pts:
        if not out or dist(out[-1], p) > tol:
            out.append(p)
    while len(out) > 1 and dist(out[0], out[-1]) <= tol:
        out.pop()
    return out


def fit_circle(pts: Sequence[Pt]) -> tuple[Pt, float, float] | None:
    """Algebraic (Kasa) circle fit. Returns (center, radius, rms_residual).

    Used by arc-based symbol detectors: PDF has no arc operator, so CAD exports
    emit door swings as bezier chains or polylines and we recover the circle.
    """
    n = len(pts)
    if n < 3:
        return None
    mx = sum(p.x for p in pts) / n
    my = sum(p.y for p in pts) / n
    suu = suv = svv = suuu = svvv = suvv = svuu = 0.0
    for p in pts:
        u, v = p.x - mx, p.y - my
        suu += u * u
        svv += v * v
        suv += u * v
        suuu += u * u * u
        svvv += v * v * v
        suvv += u * v * v
        svuu += v * u * u
    det = suu * svv - suv * suv
    if abs(det) < 1e-12:
        return None
    b1 = (suuu + suvv) / 2.0
    b2 = (svvv + svuu) / 2.0
    uc = (b1 * svv - b2 * suv) / det
    vc = (b2 * suu - b1 * suv) / det
    center = Pt(uc + mx, vc + my)
    r = math.sqrt(uc * uc + vc * vc + (suu + svv) / n)
    resid = math.sqrt(sum((dist(p, center) - r) ** 2 for p in pts) / n)
    return center, r, resid


def arc_span(pts: Sequence[Pt], center: Pt) -> float:
    """Total turned angle along a point chain about `center`, in radians."""
    total = 0.0
    for i in range(len(pts) - 1):
        a0 = angle_of(pts[i] - center)
        a1 = angle_of(pts[i + 1] - center)
        total += abs(angle_diff(a1, a0))
    return total
