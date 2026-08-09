"""Turn a soup of line segments into walls with thickness and openings.

The central observation about CAD-exported plans: a wall is drawn as *two
parallel lines* (its faces), and an opening is where both faces stop. So rather
than chasing individual segments we cluster segments onto the infinite lines
they lie on, pair those lines across a plausible wall thickness, and read the
openings straight off the gaps in the paired coverage.

That ordering matters. Pairing raw segments first fails on any wall broken into
pieces by doors, and every real plan has those.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .geom import EPS, Pt, Seg, dist, point_seg_distance, seg_intersection
from .pdf.content import PageGeometry, Primitive

# Millimetre bounds on what counts as a wall. Interior partitions bottom out
# around 70 mm (stud) and party/basement walls run to ~400 mm.
MIN_THICKNESS = 60.0
MAX_THICKNESS = 420.0
MIN_WALL_LENGTH = 250.0

# An opening narrower than this is a drafting artefact; wider is a missing wall.
# The upper bound is generous because curtain walling and shopfronts routinely
# run several metres; anything that wide and *unglazed* matches no symbol and
# raises a warning rather than passing silently.
MIN_OPENING = 350.0
MAX_OPENING = 8000.0

# Tolerances for deciding two segments lie on the same infinite line.
ANGLE_TOL_DEG = 1.5
OFFSET_TOL = 12.0
JOIN_TOL = 25.0

# Corner reconstruction. A corner window removes the corner entirely: both
# walls stop short and nothing encloses the room. These bound how much missing
# corner we are willing to put back.
MAX_CORNER_LEG = 3000.0
CORNER_ANGLE_RANGE = (55.0, 125.0)
FREE_END_TOL = 60.0

WALL_LAYER_HINTS = ("wall", "tuong", "tường", "mur", "wand", "a-wall", "s-wall", "muro")
IGNORE_LAYER_HINTS = (
    "dim", "anno", "text", "hatch", "furn", "grid", "titl", "note",
    "north", "symb", "kich", "ghichu", "legend", "logo",
)


@dataclass
class Opening:
    """A gap in a wall. Kind is refined later by the symbol library."""

    wall: int
    t_start: float
    t_end: float
    kind: str = "opening"
    symbol: str | None = None
    confidence: float = 0.4
    bridged: bool = False   # created by corner reconstruction, not by a face gap
    meta: dict = field(default_factory=dict)

    @property
    def width(self) -> float:
        return self.t_end - self.t_start

    @property
    def t_mid(self) -> float:
        return (self.t_start + self.t_end) / 2.0


@dataclass
class Wall:
    a: Pt
    b: Pt
    thickness: float
    layer: str | None = None
    openings: list[Opening] = field(default_factory=list)
    source: str = "paired-faces"

    @property
    def seg(self) -> Seg:
        return Seg(self.a, self.b)

    def length(self) -> float:
        return dist(self.a, self.b)

    def dir(self) -> Pt:
        return (self.b - self.a).unit()

    def point_at_t(self, t: float) -> Pt:
        d = self.dir()
        return Pt(self.a.x + d.x * t, self.a.y + d.y * t)


@dataclass
class _Line:
    """A cluster of collinear segments: an infinite line plus its coverage."""

    theta: float
    rho: float
    intervals: list[tuple[float, float]] = field(default_factory=list)
    layers: set[str] = field(default_factory=set)
    origin: Pt = field(default_factory=lambda: Pt(0.0, 0.0))

    def direction(self) -> Pt:
        return Pt(math.cos(self.theta), math.sin(self.theta))

    def normal(self) -> Pt:
        return Pt(-math.sin(self.theta), math.cos(self.theta))

    def point_at(self, t: float) -> Pt:
        d = self.direction()
        n = self.normal()
        return Pt(n.x * self.rho + d.x * t, n.y * self.rho + d.y * t)

    def coverage(self) -> list[tuple[float, float]]:
        return merge_intervals(self.intervals, JOIN_TOL)

    def extent(self) -> tuple[float, float]:
        cov = self.coverage()
        return (cov[0][0], cov[-1][1]) if cov else (0.0, 0.0)

    def covered_length(self) -> float:
        return sum(b - a for a, b in self.coverage())


# -- interval algebra --------------------------------------------------------
def merge_intervals(iv: list[tuple[float, float]], gap: float = 0.0) -> list[tuple[float, float]]:
    if not iv:
        return []
    out: list[list[float]] = []
    for a, b in sorted(iv):
        if a > b:
            a, b = b, a
        if out and a <= out[-1][1] + gap:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def intersect_intervals(
    x: list[tuple[float, float]], y: list[tuple[float, float]]
) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    i = j = 0
    while i < len(x) and j < len(y):
        lo = max(x[i][0], y[j][0])
        hi = min(x[i][1], y[j][1])
        if hi > lo:
            out.append((lo, hi))
        if x[i][1] < y[j][1]:
            i += 1
        else:
            j += 1
    return out


def complement(iv: list[tuple[float, float]], lo: float, hi: float) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    cursor = lo
    for a, b in merge_intervals(iv):
        if b <= lo or a >= hi:
            continue
        a, b = max(a, lo), min(b, hi)
        if a > cursor:
            out.append((cursor, a))
        cursor = max(cursor, b)
    if cursor < hi:
        out.append((cursor, hi))
    return out


# -- segment harvesting ------------------------------------------------------
def segments_from(prims: list[Primitive], mm_per_pt: float) -> list[tuple[Seg, str | None]]:
    """Explode primitives to segments in millimetre space."""
    out: list[tuple[Seg, str | None]] = []
    for p in prims:
        pts = [Pt(q.x * mm_per_pt, q.y * mm_per_pt) for q in p.points]
        pairs = list(zip(pts, pts[1:], strict=False))
        if p.closed and len(pts) > 2:
            pairs.append((pts[-1], pts[0]))
        for a, b in pairs:
            if dist(a, b) > 1.0:
                out.append((Seg(a, b), p.layer))
    return out


def choose_wall_layers(layers: set[str | None]) -> set[str | None] | None:
    """Prefer explicit wall layers when the exporter gave us any."""
    named = {ly for ly in layers if ly}
    hits = {ly for ly in named if any(h in ly.lower() for h in WALL_LAYER_HINTS)}
    if hits:
        return hits
    if named:
        keep = {ly for ly in named if not any(h in ly.lower() for h in IGNORE_LAYER_HINTS)}
        if keep and len(keep) < len(named):
            return keep | {None}
    return None


def cluster_lines(segs: list[tuple[Seg, str | None]]) -> list[_Line]:
    """Group segments onto shared infinite lines (theta, rho)."""
    angle_tol = math.radians(ANGLE_TOL_DEG)
    buckets: dict[int, list[_Line]] = {}
    lines: list[_Line] = []

    for seg, layer in segs:
        v = seg.vec
        theta = math.atan2(v.y, v.x) % math.pi
        n = Pt(-math.sin(theta), math.cos(theta))
        rho = seg.a.dot(n)
        d = Pt(math.cos(theta), math.sin(theta))
        t0, t1 = seg.a.dot(d), seg.b.dot(d)
        if t0 > t1:
            t0, t1 = t1, t0

        key = int(theta / angle_tol)
        found: _Line | None = None
        for k in (key - 1, key, key + 1):
            for ln in buckets.get(k, ()):
                dth = abs(ln.theta - theta)
                dth = min(dth, math.pi - dth)
                if dth > angle_tol:
                    continue
                # Compare rho in this segment's own frame: near theta==0/pi the
                # normal flips sign, so a raw difference is not meaningful.
                if abs(ln.rho * (1 if abs(ln.theta - theta) < math.pi / 2 else -1) - rho) > OFFSET_TOL:
                    continue
                found = ln
                break
            if found:
                break
        if found is None:
            found = _Line(theta=theta, rho=rho, origin=seg.a)
            lines.append(found)
            buckets.setdefault(key, []).append(found)
        found.intervals.append((t0, t1))
        if layer:
            found.layers.add(layer)
    return lines


def pair_lines(lines: list[_Line]) -> list[Wall]:
    """Pair parallel lines separated by a plausible wall thickness."""
    angle_tol = math.radians(ANGLE_TOL_DEG)
    walls: list[Wall] = []
    n = len(lines)
    order = sorted(range(n), key=lambda i: lines[i].theta)

    for ii in range(n):
        i = order[ii]
        a = lines[i]
        for jj in range(ii + 1, n):
            j = order[jj]
            b = lines[j]
            dth = abs(a.theta - b.theta)
            dth = min(dth, math.pi - dth)
            if dth > angle_tol:
                if b.theta - a.theta > angle_tol and b.theta < math.pi - angle_tol:
                    break  # sorted by theta: nothing further can match
                continue
            gap = abs(a.rho - b.rho)
            if not (MIN_THICKNESS <= gap <= MAX_THICKNESS):
                continue
            cov_a, cov_b = a.coverage(), b.coverage()
            both = intersect_intervals(cov_a, cov_b)
            union = merge_intervals(cov_a + cov_b)
            if not union:
                continue
            lo, hi = union[0][0], union[-1][1]
            solid = sum(x[1] - x[0] for x in both)
            if hi - lo < MIN_WALL_LENGTH:
                continue
            # Require the faces to genuinely run alongside each other, not merely
            # to be two unrelated lines that happen to be 110 mm apart.
            shorter = min(a.covered_length(), b.covered_length())
            if shorter < EPS or solid < 0.45 * shorter:
                continue

            mid_rho = (a.rho + b.rho) / 2.0
            centre = _Line(theta=a.theta, rho=mid_rho)
            wall = Wall(
                a=centre.point_at(lo),
                b=centre.point_at(hi),
                thickness=gap,
                layer=next(iter(sorted(a.layers | b.layers)), None),
            )
            for g0, g1 in complement(both, lo, hi):
                if MIN_OPENING <= g1 - g0 <= MAX_OPENING:
                    wall.openings.append(
                        Opening(wall=-1, t_start=g0 - lo, t_end=g1 - lo)
                    )
            walls.append(wall)
    return walls


def suppress_nested(walls: list[Wall]) -> list[Wall]:
    """Drop walls whose centreline runs inside a thicker wall.

    Window glazing lines and door thresholds sit inside the wall body and can
    pair up into a phantom thin wall on top of the real one.
    """
    keep: list[Wall] = []
    order = sorted(walls, key=lambda w: -w.thickness * w.length())
    for w in order:
        nested = False
        for other in keep:
            if other is w or other.thickness <= w.thickness + EPS:
                continue
            od = other.dir()
            if abs(od.cross(w.dir())) > math.sin(math.radians(2 * ANGLE_TOL_DEG)):
                continue
            on = od.perp()
            d0 = abs((w.a - other.a).dot(on))
            d1 = abs((w.b - other.a).dot(on))
            if max(d0, d1) > other.thickness / 2.0:
                continue
            t0 = (w.a - other.a).dot(od)
            t1 = (w.b - other.a).dot(od)
            olen = other.length()
            if min(t0, t1) > olen or max(t0, t1) < 0:
                continue
            nested = True
            break
        if not nested:
            keep.append(w)
    return keep


def dedupe_walls(walls: list[Wall]) -> list[Wall]:
    """Collapse walls that describe the same run (from redundant line pairings)."""
    keep: list[Wall] = []
    for w in sorted(walls, key=lambda x: -x.length()):
        dup = False
        for k in keep:
            if abs(k.thickness - w.thickness) > OFFSET_TOL:
                continue
            if abs(k.dir().cross(w.dir())) > math.sin(math.radians(2 * ANGLE_TOL_DEG)):
                continue
            if dist(k.seg.midpoint(), w.seg.midpoint()) > max(20.0, 0.1 * k.length()):
                continue
            kn = k.dir().perp()
            if abs((w.a - k.a).dot(kn)) > OFFSET_TOL:
                continue
            dup = True
            break
        if not dup:
            keep.append(w)
    return keep


def _endpoint_is_free(p: Pt, owner: int, walls: list[Wall], tol: float) -> bool:
    """True when nothing else joins the wall here.

    A free end is one that neither meets another wall's endpoint nor lands on
    another wall's run -- so ordinary corners and T-junctions are excluded, and
    what remains is a wall that genuinely stops in mid-air.
    """
    for j, other in enumerate(walls):
        if j == owner:
            continue
        if dist(p, other.a) <= tol or dist(p, other.b) <= tol:
            return False
        if point_seg_distance(p, other.seg) <= tol:
            return False
    return True


def bridge_corners(walls: list[Wall], tol: float = FREE_END_TOL) -> list[Wall]:
    """Put back corners that a corner window removed.

    Two walls whose free ends point at a shared, missing corner are extended to
    meet, and the length each one gained is recorded as an opening. Without
    this the cycle never closes and the room is simply lost -- so a corner
    window is not a symbol-library problem, it is a wall-extraction one.
    """
    ends: list[tuple[int, str, Pt]] = []
    for i, w in enumerate(walls):
        if w.length() < EPS:
            continue
        for which in ("a", "b"):
            p = w.a if which == "a" else w.b
            if _endpoint_is_free(p, i, walls, tol):
                ends.append((i, which, p))

    candidates: list[tuple[float, int, str, float, int, str, float, Pt]] = []
    for x in range(len(ends)):
        i, end_i, pi = ends[x]
        wi = walls[i]
        di = wi.dir() if end_i == "b" else wi.dir() * -1.0
        for y in range(x + 1, len(ends)):
            j, end_j, pj = ends[y]
            if i == j:
                continue
            wj = walls[j]
            dj = wj.dir() if end_j == "b" else wj.dir() * -1.0

            # Both directions point at the missing corner, so the angle between
            # them is the corner angle itself.
            angle = math.degrees(math.acos(max(-1.0, min(1.0, di.dot(dj)))))
            if not (CORNER_ANGLE_RANGE[0] <= angle <= CORNER_ANGLE_RANGE[1]):
                continue
            corner = seg_intersection(
                Seg(pi, pi + di * (MAX_CORNER_LEG * 2)),
                Seg(pj, pj + dj * (MAX_CORNER_LEG * 2)),
                tol=1e-9,
            )
            if corner is None:
                continue
            ext_i = (corner - pi).dot(di)
            ext_j = (corner - pj).dot(dj)
            if not (0.0 < ext_i <= MAX_CORNER_LEG and 0.0 < ext_j <= MAX_CORNER_LEG):
                continue
            if dist(pi, corner) > ext_i + tol or dist(pj, corner) > ext_j + tol:
                continue
            candidates.append((ext_i + ext_j, i, end_i, ext_i, j, end_j, ext_j, corner))

    used: set[tuple[int, str]] = set()
    for _total, i, end_i, ext_i, j, end_j, ext_j, corner in sorted(candidates, key=lambda c: c[0]):
        if (i, end_i) in used or (j, end_j) in used:
            continue
        used.add((i, end_i))
        used.add((j, end_j))
        for idx, which, ext in ((i, end_i, ext_i), (j, end_j, ext_j)):
            w = walls[idx]
            old_len = w.length()
            if which == "b":
                w.b = corner
                w.openings.append(
                    Opening(wall=idx, t_start=old_len, t_end=old_len + ext, bridged=True)
                )
            else:
                w.a = corner
                for op in w.openings:
                    op.t_start += ext
                    op.t_end += ext
                w.openings.append(Opening(wall=idx, t_start=0.0, t_end=ext, bridged=True))
            w.source = "corner-bridged"
    return walls


def extract_walls(geo: PageGeometry, mm_per_pt: float) -> list[Wall]:
    all_segs = segments_from([p for p in geo.primitives if p.stroked or p.filled], mm_per_pt)
    if not all_segs:
        return []
    chosen = choose_wall_layers({ly for _, ly in all_segs})
    segs = [(s, ly) for s, ly in all_segs if chosen is None or ly in chosen]
    if len(segs) < 4:
        segs = all_segs

    walls = dedupe_walls(suppress_nested(pair_lines(cluster_lines(segs))))
    walls = bridge_corners(walls)
    walls.sort(key=lambda w: (-w.length(), w.a.x, w.a.y))
    for i, w in enumerate(walls):
        w.openings.sort(key=lambda o: o.t_start)
        for o in w.openings:
            o.wall = i
    return walls
