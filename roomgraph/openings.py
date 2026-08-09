"""Run the symbol library over the plan.

Each wall gap becomes an `OpeningContext` in its own local frame, so a detector
never has to think about which way the wall runs. Whatever the library says
wins: the opening's kind, the symbol that claimed it, and the confidence.
"""

from __future__ import annotations

from dataclasses import dataclass

from .geom import Pt, bbox, point_in_polygon
from .pdf.content import PageGeometry
from .rooms import Room
from .symbols import OpeningContext, RoomContext, best_match, symbols_for
from .walls import Opening, Wall

# How far around an opening to look, as a multiple of its width. A door swing
# reaches one leaf-width out, so this needs headroom.
SEARCH_ALONG = 1.4
SEARCH_ACROSS = 1.5


@dataclass
class RoomFeature:
    room: str
    symbol: str
    kind: str
    confidence: float
    meta: dict


def _mm_polylines(geo: PageGeometry, mm_per_pt: float) -> list[tuple[list[Pt], str | None]]:
    out: list[tuple[list[Pt], str | None]] = []
    for p in geo.primitives:
        pts = [Pt(q.x * mm_per_pt, q.y * mm_per_pt) for q in p.points]
        if p.closed and len(pts) > 2:
            pts = pts + [pts[0]]
        if len(pts) >= 2:
            out.append((pts, p.layer))
    return out


def classify_openings(
    walls: list[Wall],
    geo: PageGeometry,
    mm_per_pt: float,
) -> list[Opening]:
    strokes = _mm_polylines(geo, mm_per_pt)
    boxes = [bbox(pts) for pts, _ in strokes]

    classified: list[Opening] = []
    for wi, wall in enumerate(walls):
        d = wall.dir()
        n = d.perp()
        for op in wall.openings:
            origin = wall.point_at_t(op.t_mid)
            reach_x = op.width * SEARCH_ALONG
            reach_y = op.width * SEARCH_ACROSS
            radius = max(reach_x, reach_y)

            local: list[list[Pt]] = []
            layers: list[str | None] = []
            for (pts, layer), (x0, y0, x1, y1) in zip(strokes, boxes, strict=False):
                if (
                    x1 < origin.x - radius
                    or x0 > origin.x + radius
                    or y1 < origin.y - radius
                    or y0 > origin.y + radius
                ):
                    continue
                lp = [Pt((q - origin).dot(d), (q - origin).dot(n)) for q in pts]
                if not any(abs(q.x) <= reach_x and abs(q.y) <= reach_y for q in lp):
                    continue
                local.append(lp)
                layers.append(layer)

            ctx = OpeningContext(
                width=op.width,
                wall_thickness=wall.thickness,
                strokes=local,
                wall_length=wall.length(),
                t_mid=op.t_mid,
                bridged=op.bridged,
                layers=layers,
            )
            hit = best_match(ctx, "opening")
            if hit:
                sym, match = hit
                op.kind = match.kind
                op.symbol = sym.id
                op.confidence = round(match.confidence, 3)
                op.meta = dict(match.meta)
            else:
                op.kind = "opening"
                op.symbol = None
                op.confidence = 0.15
                op.meta = {"reason": "no symbol matched"}
            op.wall = wi
            classified.append(op)
    return classified


def detect_room_features(
    rooms: list[Room],
    geo: PageGeometry,
    mm_per_pt: float,
    min_confidence: float = 0.35,
) -> list[RoomFeature]:
    strokes = _mm_polylines(geo, mm_per_pt)

    # Assign each stroke to at most one room -- the one holding most of it.
    # A fitting drawn tight against a wall otherwise counts for both sides.
    owned: dict[int, list[tuple[list[Pt], str | None]]] = {}
    for pts, layer in strokes:
        best, best_score = -1, 0
        for i, room in enumerate(rooms):
            score = sum(1 for q in pts if point_in_polygon(q, room.polygon))
            if score > best_score:
                best, best_score = i, score
        if best >= 0 and best_score >= max(1, len(pts) // 2):
            owned.setdefault(best, []).append((pts, layer))

    features: list[RoomFeature] = []
    for index, room in enumerate(rooms):
        held = owned.get(index, [])
        if not held:
            continue
        inside = [pts for pts, _ in held]
        layers = [layer for _, layer in held]
        ctx = RoomContext(
            polygon=room.polygon,
            strokes=inside,
            area_m2=room.area_gross_m2,
            layers=layers,
        )
        # Room features are not mutually exclusive the way openings are: a
        # bathroom can hold sanitary fittings *and* a stair. So every room-scope
        # symbol reports independently, rather than the best one winning.
        for sym in symbols_for("room"):
            try:
                match = sym.detect(ctx)
            except Exception:
                continue
            if match is None or match.confidence < min_confidence:
                continue
            features.append(
                RoomFeature(
                    room=room.id,
                    symbol=sym.id,
                    kind=match.kind,
                    confidence=round(match.confidence, 3),
                    meta=dict(match.meta),
                )
            )
    return features
