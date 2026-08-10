"""The structured model, and the one function that produces it.

`extract()` runs the whole pipeline and returns a `PlanModel`. Every exporter
takes that model and nothing else, so adding an output format never touches the
geometry code.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from .adjacency import RoomGraph, build_graph, opening_ids
from .geom import bbox
from .openings import (
    PlanFeature,
    RoomFeature,
    classify_openings,
    detect_plan_features,
    detect_room_features,
)
from .pdf.content import PageGeometry, read_pdf
from .planar import Arrangement, build_arrangement
from .rooms import Room, build_rooms
from .scale import ScaleResult, determine_scale
from .walls import MAX_THICKNESS, MIN_THICKNESS, Opening, Wall, extract_walls

SCHEMA_VERSION = "1.0"


@dataclass
class PlanModel:
    source: str
    page: int
    scale: ScaleResult
    walls: list[Wall] = field(default_factory=list)
    rooms: list[Room] = field(default_factory=list)
    openings: list[Opening] = field(default_factory=list)
    graph: RoomGraph = field(default_factory=RoomGraph)
    features: list[RoomFeature] = field(default_factory=list)
    plan_features: list[PlanFeature] = field(default_factory=list)
    arrangement: Arrangement | None = None
    geometry: PageGeometry | None = None
    warnings: list[str] = field(default_factory=list)
    _op_ids: dict[int, str] = field(default_factory=dict, repr=False)

    @property
    def total_area_m2(self) -> float:
        return round(sum(r.area_gross_m2 for r in self.rooms), 2)

    def bounds(self) -> tuple[float, float, float, float]:
        pts = [p for r in self.rooms for p in r.polygon]
        pts += [w.a for w in self.walls] + [w.b for w in self.walls]
        return bbox(pts) if pts else (0.0, 0.0, 0.0, 0.0)

    def opening_id(self, op: Opening) -> str:
        return self._op_ids.get(id(op), "O000")

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for op in self.openings:
            out[op.kind] = out.get(op.kind, 0) + 1
        return out


def extract(
    path: str,
    page: int = 0,
    scale: str | None = None,
    min_room_area_m2: float = 0.7,
) -> PlanModel:
    geo = read_pdf(path, page_index=page)
    scale_result = determine_scale(geo, explicit=scale)

    walls = extract_walls(geo, scale_result.mm_per_pt)
    arrangement = build_arrangement(walls)
    rooms = build_rooms(
        arrangement, walls, geo.texts, scale_result.mm_per_pt, min_area_m2=min_room_area_m2
    )
    openings = classify_openings(walls, geo, scale_result.mm_per_pt)
    graph = build_graph(arrangement, rooms, walls, openings)
    features = detect_room_features(rooms, geo, scale_result.mm_per_pt)
    plan_features = detect_plan_features(geo, scale_result.mm_per_pt, rooms)

    model = PlanModel(
        source=os.path.basename(path),
        page=page,
        scale=scale_result,
        walls=walls,
        rooms=rooms,
        openings=openings,
        graph=graph,
        features=features,
        plan_features=plan_features,
        arrangement=arrangement,
        geometry=geo,
    )
    model._op_ids = opening_ids(walls, openings)
    model.warnings = _audit(model)
    return model


def _audit(model: PlanModel) -> list[str]:
    """Say plainly where the result should not be trusted."""
    warn: list[str] = []

    if model.scale.confidence < 0.5:
        warn.append(
            f"scale came from '{model.scale.source}' at confidence "
            f"{model.scale.confidence:.2f} -- every area depends on it; "
            f"pass --scale 1:N to be sure"
        )
    if not model.walls:
        warn.append(
            "no walls found: the page may be a raster scan, or the scale may be wrong "
            "(wall faces are only paired between "
            f"{int(MIN_THICKNESS)} and {int(MAX_THICKNESS)} mm apart)"
        )
    elif not model.rooms:
        warn.append(
            f"no rooms found: {len(model.walls)} wall(s) were detected but none enclose "
            f"a space -- usually a wrong scale, or wall faces drawn on layers we skipped"
        )

    mismatched = [r for r in model.rooms if r.area_check() == "mismatch"]
    if mismatched:
        names = ", ".join(f"{r.name or r.id} ({r.area_delta_pct:+.1f}%)" for r in mismatched[:4])
        warn.append(f"computed area disagrees with the drawing's own label for {names}")

    unnamed = [r for r in model.rooms if not r.name]
    if unnamed and len(unnamed) == len(model.rooms):
        warn.append("no room found a text label; names and categories are unavailable")

    weak = [op for op in model.openings if op.confidence < 0.35]
    if weak:
        warn.append(f"{len(weak)} opening(s) matched no symbol confidently")

    if model.rooms and not model.graph.is_connected():
        warn.append(
            "the room graph is disconnected: some rooms have no doorway, "
            "which usually means a missed opening"
        )
    if model.rooms and not model.graph.entrances:
        warn.append("no entrance found: no opening connects any room to the outside")

    # The drawing's own statements, checked against what we measured. Each of
    # these is a witness we did not have to trust in the first place.
    for feature in model.plan_features:
        if feature.symbol == "dimension_chain" and not feature.meta.get("adds_up", True):
            warn.append(
                f"a dimension chain does not add up: its parts total "
                f"{feature.meta.get('stated_mm')} mm over a span measuring "
                f"{feature.meta.get('measured_mm')} mm "
                f"({feature.meta.get('delta_pct'):+.1f}%)"
            )
        if feature.symbol == "door_schedule":
            listed = feature.meta.get("listed", 0)
            found = model.counts().get("door", 0)
            if listed != found:
                warn.append(
                    f"the door schedule lists {listed} door(s) but {found} "
                    f"were found on the plan"
                )
    for feature in model.plan_features:
        if feature.symbol != "scale_bar" or feature.meta.get("confirms_scale"):
            continue
        warn.append(
            f"the scale bar disagrees with the scale in use: it is labelled "
            f"{feature.meta.get('stated_m')} m but measures "
            f"{feature.meta.get('measured_m')} m "
            f"({feature.meta.get('delta_pct'):+.1f}%)"
        )

    return warn
