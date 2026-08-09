"""GeoJSON: rooms as polygons, walls as lines, openings as points.

By default coordinates are **metres on a local engineering grid**, not degrees.
That is what indoor tooling expects, but it is not what RFC 7946 says, so the
file carries an explicit `roomgraph:crs` marker rather than pretending.

Pass a `geo_origin` of (lat, lon) to place the plan on the earth instead. The
projection is a local equirectangular one anchored at that point -- accurate to
well under a millimetre over a building, and readable by any GIS.
"""

from __future__ import annotations

import json
import math
from typing import Any

from ..model import PlanModel

EARTH_R = 6378137.0


class _Projector:
    def __init__(
        self,
        origin_mm: tuple[float, float],
        geo_origin: tuple[float, float] | None,
        rotation_deg: float = 0.0,
    ) -> None:
        self.ox, self.oy = origin_mm
        self.geo = geo_origin
        self.rot = math.radians(rotation_deg)

    def __call__(self, p) -> list[float]:
        x = (p.x - self.ox) / 1000.0
        y = (p.y - self.oy) / 1000.0
        if self.rot:
            c, s = math.cos(self.rot), math.sin(self.rot)
            x, y = x * c - y * s, x * s + y * c
        if self.geo is None:
            return [round(x, 4), round(y, 4)]
        lat0, lon0 = self.geo
        lat = lat0 + math.degrees(y / EARTH_R)
        lon = lon0 + math.degrees(x / (EARTH_R * math.cos(math.radians(lat0))))
        return [round(lon, 9), round(lat, 9)]


def to_dict(
    model: PlanModel,
    geo_origin: tuple[float, float] | None = None,
    rotation_deg: float = 0.0,
    include: tuple[str, ...] = ("rooms", "walls", "openings"),
) -> dict[str, Any]:
    x0, y0, _, _ = model.bounds()
    proj = _Projector((x0, y0), geo_origin, rotation_deg)
    features: list[dict[str, Any]] = []

    if "rooms" in include:
        for r in model.rooms:
            ring = [proj(p) for p in r.polygon]
            if ring and ring[0] != ring[-1]:
                ring.append(ring[0])
            features.append(
                {
                    "type": "Feature",
                    "id": r.id,
                    "geometry": {"type": "Polygon", "coordinates": [ring]},
                    "properties": {
                        "layer": "room",
                        "name": r.name,
                        "category": r.category,
                        "area_gross_m2": r.area_gross_m2,
                        "area_net_m2": r.area_net_m2,
                        "perimeter_m": r.perimeter_m,
                        "area_check": r.area_check(),
                        "neighbours": model.graph.neighbours(r.id),
                    },
                }
            )

    if "walls" in include:
        for i, w in enumerate(model.walls):
            features.append(
                {
                    "type": "Feature",
                    "id": f"W{i + 1:03d}",
                    "geometry": {"type": "LineString", "coordinates": [proj(w.a), proj(w.b)]},
                    "properties": {
                        "layer": "wall",
                        "thickness_mm": round(w.thickness, 1),
                        "length_mm": round(w.length(), 1),
                        "cad_layer": w.layer,
                    },
                }
            )

    if "openings" in include:
        for op in model.openings:
            if not (0 <= op.wall < len(model.walls)):
                continue
            wall = model.walls[op.wall]
            features.append(
                {
                    "type": "Feature",
                    "id": model.opening_id(op),
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [
                            proj(wall.point_at_t(op.t_start)),
                            proj(wall.point_at_t(op.t_end)),
                        ],
                    },
                    "properties": {
                        "layer": "opening",
                        "kind": op.kind,
                        "symbol": op.symbol,
                        "confidence": op.confidence,
                        "width_mm": round(op.width, 1),
                    },
                }
            )

    doc: dict[str, Any] = {
        "type": "FeatureCollection",
        "features": features,
        "roomgraph:source": model.source,
        "roomgraph:crs": (
            "EPSG:4326"
            if geo_origin
            else "local engineering grid, metres, origin at plan bounds min corner"
        ),
    }
    return doc


def dumps(model: PlanModel, **kwargs) -> str:
    return json.dumps(to_dict(model, **kwargs), indent=2, ensure_ascii=False)


def write(model: PlanModel, path: str, **kwargs) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(dumps(model, **kwargs))
        fh.write("\n")
