"""Planar subdivision: wall centrelines in, room faces out.

Walls are snapped, split at every crossing and T-junction, then walked as a
half-edge structure. Taking the next dart *clockwise* around each vertex
enumerates the minimal cycles -- the faces. Interior faces come out
counter-clockwise (positive area); the single negative-area face is the
unbounded outside.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .geom import EPS, Pt, Seg, angle_of, dist, polygon_area, project_param, seg_intersection
from .walls import Wall

SNAP_TOL = 30.0  # mm; CAD endpoints rarely miss by more than this


@dataclass
class Dart:
    """A directed edge. `twin` is the same edge the other way."""

    index: int
    origin: int
    dest: int
    edge: int
    wall: int | None = None
    face: int = -1
    next: int = -1


@dataclass
class Face:
    index: int
    darts: list[int]
    ring: list[Pt]
    area: float

    @property
    def is_outer(self) -> bool:
        return self.area <= 0.0


@dataclass
class Arrangement:
    vertices: list[Pt] = field(default_factory=list)
    darts: list[Dart] = field(default_factory=list)
    faces: list[Face] = field(default_factory=list)
    edge_walls: dict[int, int] = field(default_factory=dict)

    def inner_faces(self) -> list[Face]:
        return [f for f in self.faces if not f.is_outer]


class _Snapper:
    """Grid-bucketed point welding."""

    def __init__(self, tol: float) -> None:
        self.tol = tol
        self.cell = max(tol, 1e-6)
        self.buckets: dict[tuple[int, int], list[int]] = {}
        self.points: list[Pt] = []

    def add(self, p: Pt) -> int:
        cx, cy = int(math.floor(p.x / self.cell)), int(math.floor(p.y / self.cell))
        best, best_d = -1, self.tol
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for i in self.buckets.get((cx + dx, cy + dy), ()):
                    d = dist(self.points[i], p)
                    if d <= best_d:
                        best, best_d = i, d
        if best >= 0:
            return best
        idx = len(self.points)
        self.points.append(p)
        self.buckets.setdefault((cx, cy), []).append(idx)
        return idx


def _split_all(segments: list[tuple[Seg, int]], tol: float) -> list[tuple[Seg, int]]:
    """Split every segment at crossings and at endpoints lying on its interior.

    The T-junction case is the one that matters: a partition wall ending against
    a party wall shares no endpoint with it, and without a split the two rooms
    on either side merge into one.
    """
    cuts: list[list[float]] = [[] for _ in segments]
    endpoints = [p for s, _ in segments for p in (s.a, s.b)]

    for i, (s1, _) in enumerate(segments):
        len1 = s1.length()
        if len1 < EPS:
            continue
        for j in range(i + 1, len(segments)):
            s2 = segments[j][0]
            if s2.length() < EPS:
                continue
            p = seg_intersection(s1, s2)
            if p is None:
                continue
            t1 = project_param(p, s1)
            t2 = project_param(p, s2)
            if tol / len1 < t1 < 1 - tol / len1:
                cuts[i].append(t1)
            len2 = s2.length()
            if tol / len2 < t2 < 1 - tol / len2:
                cuts[j].append(t2)

    for i, (s, _) in enumerate(segments):
        ln = s.length()
        if ln < EPS:
            continue
        for p in endpoints:
            t = project_param(p, s)
            if not (tol / ln < t < 1 - tol / ln):
                continue
            if dist(s.point_at(t), p) <= tol:
                cuts[i].append(t)

    out: list[tuple[Seg, int]] = []
    for i, (s, wall_idx) in enumerate(segments):
        ts = sorted({0.0, 1.0} | {round(t, 9) for t in cuts[i]})
        for a, b in zip(ts, ts[1:], strict=False):
            pa, pb = s.point_at(a), s.point_at(b)
            if dist(pa, pb) > tol:
                out.append((Seg(pa, pb), wall_idx))
    return out


def build_arrangement(walls: list[Wall], snap_tol: float = SNAP_TOL) -> Arrangement:
    raw = [(w.seg, i) for i, w in enumerate(walls) if w.length() > EPS]
    pieces = _split_all(raw, snap_tol)

    snap = _Snapper(snap_tol)
    edges: dict[tuple[int, int], int] = {}
    arr = Arrangement()

    for seg, wall_idx in pieces:
        u = snap.add(seg.a)
        v = snap.add(seg.b)
        if u == v:
            continue
        key = (min(u, v), max(u, v))
        if key in edges:
            continue
        edges[key] = len(edges)
        arr.edge_walls[edges[key]] = wall_idx

    arr.vertices = snap.points

    # Prune degree-1 vertices: dangling stubs cannot bound a room and would
    # otherwise show up as zero-width spikes in the face rings.
    alive = dict.fromkeys(edges.keys(), True)
    while True:
        deg: dict[int, int] = {}
        for (u, v), _ in edges.items():
            if not alive[(u, v)]:
                continue
            deg[u] = deg.get(u, 0) + 1
            deg[v] = deg.get(v, 0) + 1
        dead = {k for k, d in deg.items() if d < 2}
        if not dead:
            break
        changed = False
        for key in edges:
            if alive[key] and (key[0] in dead or key[1] in dead):
                alive[key] = False
                changed = True
        if not changed:
            break

    for (u, v), eid in edges.items():
        if not alive[(u, v)]:
            continue
        d1 = Dart(len(arr.darts), u, v, eid, arr.edge_walls.get(eid))
        arr.darts.append(d1)
        d2 = Dart(len(arr.darts), v, u, eid, arr.edge_walls.get(eid))
        arr.darts.append(d2)

    if not arr.darts:
        return arr

    outgoing: dict[int, list[int]] = {}
    for d in arr.darts:
        outgoing.setdefault(d.origin, []).append(d.index)
    for v, ds in outgoing.items():
        ds.sort(key=lambda i: angle_of(arr.vertices[arr.darts[i].dest] - arr.vertices[v]))

    def twin(i: int) -> int:
        return i ^ 1

    for d in arr.darts:
        ring = outgoing[d.dest]
        k = ring.index(twin(d.index))
        d.next = ring[(k - 1) % len(ring)]

    for d in arr.darts:
        if d.face != -1:
            continue
        fid = len(arr.faces)
        cycle: list[int] = []
        cur = d.index
        for _ in range(len(arr.darts) + 1):
            if arr.darts[cur].face != -1:
                break
            arr.darts[cur].face = fid
            cycle.append(cur)
            cur = arr.darts[cur].next
            if cur == d.index:
                break
        if not cycle:
            continue
        ring = [arr.vertices[arr.darts[i].origin] for i in cycle]
        arr.faces.append(Face(fid, cycle, ring, polygon_area(ring)))

    return arr


def face_neighbours(arr: Arrangement, face: Face) -> dict[int, list[int]]:
    """Map neighbouring face index -> the darts shared with it."""
    out: dict[int, list[int]] = {}
    for di in face.darts:
        other = arr.darts[di ^ 1].face
        if other == face.index or other < 0:
            continue
        out.setdefault(other, []).append(di)
    return out
