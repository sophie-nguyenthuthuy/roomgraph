"""Canonical JSON. Every other exporter is a projection of this.

Coordinates are millimetres in the PDF's own frame (origin bottom-left of the
media box, y up). Areas are square metres. Nothing here is rounded beyond what
the drawing can support: 0.1 mm on coordinates, 1 cm2 on areas.
"""

from __future__ import annotations

import json
from typing import Any

from ..model import SCHEMA_VERSION, PlanModel


def _pt(p) -> list[float]:
    return [round(p.x, 1), round(p.y, 1)]


def _ring(pts) -> list[list[float]]:
    return [_pt(p) for p in pts]


def to_dict(model: PlanModel) -> dict[str, Any]:
    x0, y0, x1, y1 = model.bounds()
    doc: dict[str, Any] = {
        "schema": f"roomgraph/{SCHEMA_VERSION}",
        "source": {"file": model.source, "page": model.page},
        "units": {"length": "mm", "area": "m2"},
        "scale": model.scale.to_dict(),
        "bounds_mm": [round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1)],
        "summary": {
            "rooms": len(model.rooms),
            "walls": len(model.walls),
            "openings": len(model.openings),
            "total_area_m2": model.total_area_m2,
            "by_kind": model.counts(),
        },
        "rooms": [],
        "walls": [],
        "openings": [],
        "graph": {"nodes": model.graph.nodes, "edges": [], "exterior": []},
        "features": [],
        "plan_features": [],
        "warnings": model.warnings,
    }

    for r in model.rooms:
        doc["rooms"].append(
            {
                "id": r.id,
                "name": r.name,
                "category": r.category,
                "area_gross_m2": r.area_gross_m2,
                "area_net_m2": r.area_net_m2,
                "perimeter_m": r.perimeter_m,
                "centroid_mm": _pt(r.centroid),
                "label_point_mm": _pt(r.label_point),
                "polygon_mm": _ring(r.polygon),
                "labelled_area_m2": r.labelled_area_m2,
                "area_delta_pct": r.area_delta_pct,
                "area_check": r.area_check(),
                "texts": r.texts,
            }
        )

    for i, w in enumerate(model.walls):
        doc["walls"].append(
            {
                "id": f"W{i + 1:03d}",
                "start_mm": _pt(w.a),
                "end_mm": _pt(w.b),
                "length_mm": round(w.length(), 1),
                "thickness_mm": round(w.thickness, 1),
                "layer": w.layer,
                "openings": [model.opening_id(o) for o in w.openings],
            }
        )

    for op in model.openings:
        wall = model.walls[op.wall] if 0 <= op.wall < len(model.walls) else None
        centre = wall.point_at_t(op.t_mid) if wall else None
        doc["openings"].append(
            {
                "id": model.opening_id(op),
                "kind": op.kind,
                "symbol": op.symbol,
                "confidence": op.confidence,
                "wall": f"W{op.wall + 1:03d}" if wall else None,
                "width_mm": round(op.width, 1),
                "centre_mm": _pt(centre) if centre else None,
                "start_mm": _pt(wall.point_at_t(op.t_start)) if wall else None,
                "end_mm": _pt(wall.point_at_t(op.t_end)) if wall else None,
                "meta": op.meta,
            }
        )

    for e in model.graph.edges:
        doc["graph"]["edges"].append(
            {
                "a": e.a,
                "b": e.b,
                "kind": e.kind,
                "via": e.via,
                "symbol": e.symbol,
                "confidence": e.confidence,
                "shared_length_m": e.shared_length_m,
            }
        )
    for e in model.graph.exterior:
        doc["graph"]["exterior"].append(
            {"room": e.a, "kind": e.kind, "via": e.via, "symbol": e.symbol}
        )
    doc["graph"]["connected"] = model.graph.is_connected()

    for f in model.plan_features:
        doc["plan_features"].append(
            {
                "symbol": f.symbol,
                "kind": f.kind,
                "confidence": f.confidence,
                "meta": f.meta,
            }
        )

    for f in model.features:
        doc["features"].append(
            {
                "room": f.room,
                "symbol": f.symbol,
                "kind": f.kind,
                "confidence": f.confidence,
                "meta": f.meta,
            }
        )
    return doc


def dumps(model: PlanModel, indent: int = 2) -> str:
    return json.dumps(to_dict(model), indent=indent, ensure_ascii=False)


def write(model: PlanModel, path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(dumps(model))
        fh.write("\n")
