"""The room graph.

Two rooms are adjacent when they share wall. The edge is a *connection* when an
opening sits on the shared stretch -- that distinction is the whole point of the
graph, since it separates "these rooms touch" from "you can walk between them".

Rooms that connect to the unbounded outer face through an opening are entrances.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .geom import Pt, Seg, dist, project_param
from .planar import Arrangement, face_neighbours
from .rooms import Room
from .walls import Opening, Wall

# An opening counts as lying on a shared stretch if its centre is within this
# of the shared darts, in mm.
ON_EDGE_TOL = 60.0


@dataclass
class Connection:
    a: str
    b: str
    kind: str                # door | window | opening | wall
    via: str | None = None   # opening id, when there is one
    symbol: str | None = None
    confidence: float = 0.0
    shared_length_m: float = 0.0
    point: Pt | None = None


@dataclass
class RoomGraph:
    nodes: list[str] = field(default_factory=list)
    edges: list[Connection] = field(default_factory=list)
    exterior: list[Connection] = field(default_factory=list)

    @property
    def entrances(self) -> list[Connection]:
        """Exterior connections you can actually walk through."""
        return [c for c in self.exterior if c.kind in ("door", "opening")]

    def neighbours(self, room_id: str, walkable_only: bool = True) -> list[str]:
        out: list[str] = []
        for e in self.edges:
            if walkable_only and e.kind == "wall":
                continue
            if e.a == room_id:
                out.append(e.b)
            elif e.b == room_id:
                out.append(e.a)
        return out

    def is_connected(self) -> bool:
        """Every room reachable from the first through walkable edges."""
        if len(self.nodes) <= 1:
            return True
        seen = {self.nodes[0]}
        stack = [self.nodes[0]]
        while stack:
            for nb in self.neighbours(stack.pop()):
                if nb not in seen:
                    seen.add(nb)
                    stack.append(nb)
        return len(seen) == len(self.nodes)


def _opening_points(walls: list[Wall], openings: list[Opening]) -> list[tuple[Opening, Pt]]:
    out: list[tuple[Opening, Pt]] = []
    for op in openings:
        if 0 <= op.wall < len(walls):
            out.append((op, walls[op.wall].point_at_t(op.t_mid)))
    return out


def _openings_on(
    arr: Arrangement,
    darts: list[int],
    op_points: list[tuple[Opening, Pt]],
    used: set[int],
) -> list[tuple[Opening, Pt]]:
    """Openings whose centre lies on one of these darts."""
    found: list[tuple[Opening, Pt]] = []
    for di in darts:
        d = arr.darts[di]
        a, b = arr.vertices[d.origin], arr.vertices[d.dest]
        seg_len = dist(a, b)
        if seg_len < 1e-6:
            continue
        seg = Seg(a, b)
        for idx, (op, p) in enumerate(op_points):
            if idx in used:
                continue
            if d.wall is not None and op.wall != d.wall:
                continue
            t = project_param(p, seg)
            if not (-ON_EDGE_TOL / seg_len <= t <= 1 + ON_EDGE_TOL / seg_len):
                continue
            if dist(seg.point_at(max(0.0, min(1.0, t))), p) > ON_EDGE_TOL:
                continue
            used.add(idx)
            found.append((op, p))
    return found


def build_graph(
    arr: Arrangement,
    rooms: list[Room],
    walls: list[Wall],
    openings: list[Opening],
) -> RoomGraph:
    by_face = {r.face: r for r in rooms}
    graph = RoomGraph(nodes=[r.id for r in rooms])
    op_points = _opening_points(walls, openings)
    op_ids = {id(op): f"O{i + 1:03d}" for i, (op, _) in enumerate(op_points)}
    seen_pairs: set[tuple[int, int]] = set()
    used: set[int] = set()

    for room in rooms:
        face = arr.faces[room.face]
        for other_face, darts in face_neighbours(arr, face).items():
            neighbour = by_face.get(other_face)
            shared = sum(
                dist(arr.vertices[arr.darts[d].origin], arr.vertices[arr.darts[d].dest])
                for d in darts
            )

            if neighbour is None:
                # The other side is outside (or a space we did not keep).
                if not arr.faces[other_face].is_outer:
                    continue
                for op, p in _openings_on(arr, darts, op_points, used):
                    graph.exterior.append(
                        Connection(
                            a=room.id,
                            b="OUTSIDE",
                            kind=op.kind,
                            via=op_ids[id(op)],
                            symbol=op.symbol,
                            confidence=op.confidence,
                            shared_length_m=round(shared / 1000.0, 3),
                            point=p,
                        )
                    )
                continue

            key = (min(room.face, other_face), max(room.face, other_face))
            if key in seen_pairs:
                continue
            seen_pairs.add(key)

            found = _openings_on(arr, darts, op_points, used)
            if found:
                for op, p in found:
                    graph.edges.append(
                        Connection(
                            a=room.id,
                            b=neighbour.id,
                            kind=op.kind,
                            via=op_ids[id(op)],
                            symbol=op.symbol,
                            confidence=op.confidence,
                            shared_length_m=round(shared / 1000.0, 3),
                            point=p,
                        )
                    )
            else:
                graph.edges.append(
                    Connection(
                        a=room.id,
                        b=neighbour.id,
                        kind="wall",
                        shared_length_m=round(shared / 1000.0, 3),
                    )
                )
    return graph


def opening_ids(walls: list[Wall], openings: list[Opening]) -> dict[int, str]:
    return {id(op): f"O{i + 1:03d}" for i, (op, _) in enumerate(_opening_points(walls, openings))}
