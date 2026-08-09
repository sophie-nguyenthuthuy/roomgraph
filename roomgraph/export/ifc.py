"""Rough IFC4 export (STEP physical file).

Deliberately rough, and worth being precise about what that means. What you get:

  * a real spatial hierarchy -- Project > Site > Building > Storey
  * IfcSpace per room, extruded from its actual boundary polygon
  * IfcWallStandardCase per wall, with IfcOpeningElement voids cut for openings
  * IfcDoor / IfcWindow filling those voids

What you do not get: a third dimension that came from anywhere real. A plan has
no heights, so storey height, door height and sill height are assumptions you
can override, and they are the same for every element. Treat the output as a
massing model to bring into a BIM tool and correct -- not as a survey.

Geometry is written in world coordinates in metres, which keeps placements
trivial at the cost of the local-placement tree a native authoring tool builds.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from ..geom import Pt, polygon_area
from ..model import PlanModel

_B64 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_$"


def ifc_guid(seed: str) -> str:
    """Deterministic IFC-compressed GUID, so re-exporting is diff-clean."""
    digest = hashlib.sha256(seed.encode("utf-8")).digest()[:16]
    n = int.from_bytes(digest, "big")
    out = []
    # First character encodes 2 bits, the remaining 21 encode 6 bits each.
    for i in range(21, -1, -1):
        shift = 6 * i
        out.append(_B64[(n >> shift) & (0x3 if i == 21 else 0x3F)])
    return "".join(out)[:22]


@dataclass
class IfcOptions:
    storey_height_mm: float = 3000.0
    wall_height_mm: float = 2700.0
    door_height_mm: float = 2100.0
    window_height_mm: float = 1500.0
    window_sill_mm: float = 900.0
    project_name: str = "roomgraph extraction"
    site_name: str = "Site"
    building_name: str = "Building"
    storey_name: str = "Level 0"


class _Spf:
    """Minimal STEP physical file writer."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self._n = 0

    def add(self, entity: str) -> str:
        self._n += 1
        ref = f"#{self._n}"
        self.lines.append(f"{ref}= {entity};")
        return ref

    def body(self) -> str:
        return "\n".join(self.lines)


def _s(v: str | None) -> str:
    if v is None:
        return "$"
    escaped = v.replace("\\", "\\\\").replace("'", "\\'")
    safe = "".join(c if 32 <= ord(c) < 127 else "?" for c in escaped)
    return f"'{safe}'"


def _f(v: float) -> str:
    return f"{v:.6f}".rstrip("0").rstrip(".") or "0."


def _mm(v: float) -> str:
    return _f(v / 1000.0)


def export(model: PlanModel, opts: IfcOptions | None = None) -> str:
    o = opts or IfcOptions()
    f = _Spf()
    seed = f"{model.source}:{model.page}"

    # -- geometric context
    origin = f.add("IFCCARTESIANPOINT((0.,0.,0.))")
    axis_z = f.add("IFCDIRECTION((0.,0.,1.))")
    axis_x = f.add("IFCDIRECTION((1.,0.,0.))")
    placement3d = f.add(f"IFCAXIS2PLACEMENT3D({origin},{axis_z},{axis_x})")
    dir_north = f.add("IFCDIRECTION((0.,1.,0.))")
    context = f.add(
        f"IFCGEOMETRICREPRESENTATIONCONTEXT($,'Model',3,1.E-05,{placement3d},{dir_north})"
    )
    body_ctx = f.add(
        f"IFCGEOMETRICREPRESENTATIONSUBCONTEXT('Body','Model',*,*,*,*,{context},$,.MODEL_VIEW.,$)"
    )
    axis_ctx = f.add(
        f"IFCGEOMETRICREPRESENTATIONSUBCONTEXT('Axis','Model',*,*,*,*,{context},$,.GRAPH_VIEW.,$)"
    )

    unit_len = f.add("IFCSIUNIT(*,.LENGTHUNIT.,$,.METRE.)")
    unit_area = f.add("IFCSIUNIT(*,.AREAUNIT.,$,.SQUARE_METRE.)")
    unit_vol = f.add("IFCSIUNIT(*,.VOLUMEUNIT.,$,.CUBIC_METRE.)")
    unit_ang = f.add("IFCSIUNIT(*,.PLANEANGLEUNIT.,$,.RADIAN.)")
    units = f.add(f"IFCUNITASSIGNMENT(({unit_len},{unit_area},{unit_vol},{unit_ang}))")

    project = f.add(
        f"IFCPROJECT({_s(ifc_guid(seed + ':project'))},$,{_s(o.project_name)},"
        f"{_s('Extracted from ' + model.source)},$,$,$,({context}),{units})"
    )
    local_placement = f.add(f"IFCLOCALPLACEMENT($,{placement3d})")
    site = f.add(
        f"IFCSITE({_s(ifc_guid(seed + ':site'))},$,{_s(o.site_name)},$,$,{local_placement},"
        f"$,$,.ELEMENT.,$,$,$,$,$)"
    )
    building = f.add(
        f"IFCBUILDING({_s(ifc_guid(seed + ':building'))},$,{_s(o.building_name)},$,$,"
        f"{local_placement},$,$,.ELEMENT.,$,$,$)"
    )
    storey = f.add(
        f"IFCBUILDINGSTOREY({_s(ifc_guid(seed + ':storey'))},$,{_s(o.storey_name)},$,$,"
        f"{local_placement},$,$,.ELEMENT.,0.)"
    )
    f.add(f"IFCRELAGGREGATES({_s(ifc_guid(seed + ':agg1'))},$,$,$,{project},({site}))")
    f.add(f"IFCRELAGGREGATES({_s(ifc_guid(seed + ':agg2'))},$,$,$,{site},({building}))")
    f.add(f"IFCRELAGGREGATES({_s(ifc_guid(seed + ':agg3'))},$,$,$,{building},({storey}))")

    def polygon_solid(ring: list[Pt], height_mm: float, base_mm: float = 0.0) -> str:
        """Extruded solid from a world-space ring. IFC wants counter-clockwise."""
        pts = list(ring)
        if polygon_area(pts) < 0:
            pts = list(reversed(pts))
        refs = [f.add(f"IFCCARTESIANPOINT(({_mm(p.x)},{_mm(p.y)}))") for p in pts]
        poly = f.add(f"IFCPOLYLINE(({','.join(refs + [refs[0]])}))")
        profile = f.add(f"IFCARBITRARYCLOSEDPROFILEDEF(.AREA.,$,{poly})")
        base = f.add(f"IFCCARTESIANPOINT((0.,0.,{_mm(base_mm)}))")
        pos = f.add(f"IFCAXIS2PLACEMENT3D({base},{axis_z},{axis_x})")
        return f.add(f"IFCEXTRUDEDAREASOLID({profile},{pos},{axis_z},{_mm(height_mm)})")

    def shape(solid: str) -> str:
        rep = f.add(f"IFCSHAPEREPRESENTATION({body_ctx},'Body','SweptSolid',({solid}))")
        return f.add(f"IFCPRODUCTDEFINITIONSHAPE($,$,({rep}))")

    def rect_ring(a: Pt, b: Pt, width: float) -> list[Pt]:
        d = (b - a).unit()
        n = d.perp() * (width / 2.0)
        return [a + n, b + n, b - n, a - n]

    contained: list[str] = []
    spaces: list[str] = []

    # -- spaces
    for r in model.rooms:
        solid = polygon_solid(r.polygon, o.wall_height_mm)
        sp = f.add(
            f"IFCSPACE({_s(ifc_guid(seed + ':space:' + r.id))},$,{_s(r.name or r.id)},"
            f"{_s(r.category)},$,{local_placement},{shape(solid)},{_s(r.name or r.id)},"
            f".ELEMENT.,.INTERNAL.,$)"
        )
        spaces.append(sp)
        qto_area = f.add(
            f"IFCQUANTITYAREA('NetFloorArea',$,{unit_area},{_f(r.area_net_m2)},$)"
        )
        qto_gross = f.add(
            f"IFCQUANTITYAREA('GrossFloorArea',$,{unit_area},{_f(r.area_gross_m2)},$)"
        )
        qto = f.add(
            f"IFCELEMENTQUANTITY({_s(ifc_guid(seed + ':qto:' + r.id))},$,'BaseQuantities',$,$,"
            f"({qto_area},{qto_gross}))"
        )
        f.add(
            f"IFCRELDEFINESBYPROPERTIES({_s(ifc_guid(seed + ':qtorel:' + r.id))},$,$,$,"
            f"({sp}),{qto})"
        )

    if spaces:
        f.add(
            f"IFCRELAGGREGATES({_s(ifc_guid(seed + ':aggspaces'))},$,$,$,{storey},"
            f"({','.join(spaces)}))"
        )

    # -- walls, with their openings cut and filled
    for i, w in enumerate(model.walls):
        wid = f"W{i + 1:03d}"
        solid = polygon_solid(rect_ring(w.a, w.b, w.thickness), o.wall_height_mm)
        p1 = f.add(f"IFCCARTESIANPOINT(({_mm(w.a.x)},{_mm(w.a.y)}))")
        p2 = f.add(f"IFCCARTESIANPOINT(({_mm(w.b.x)},{_mm(w.b.y)}))")
        axis_poly = f.add(f"IFCPOLYLINE(({p1},{p2}))")
        axis_rep = f.add(
            f"IFCSHAPEREPRESENTATION({axis_ctx},'Axis','Curve2D',({axis_poly}))"
        )
        body_rep = f.add(f"IFCSHAPEREPRESENTATION({body_ctx},'Body','SweptSolid',({solid}))")
        prod = f.add(f"IFCPRODUCTDEFINITIONSHAPE($,$,({axis_rep},{body_rep}))")
        wall = f.add(
            f"IFCWALLSTANDARDCASE({_s(ifc_guid(seed + ':wall:' + wid))},$,{_s(wid)},"
            f"{_s(w.layer)},$,{local_placement},{prod},{_s(wid)})"
        )
        contained.append(wall)

        for op in w.openings:
            oid = model.opening_id(op)
            a = w.point_at_t(op.t_start)
            b = w.point_at_t(op.t_end)
            is_window = op.kind == "window"
            height = o.window_height_mm if is_window else o.door_height_mm
            base = o.window_sill_mm if is_window else 0.0
            void_solid = polygon_solid(
                rect_ring(a, b, w.thickness * 1.2), height, base
            )
            void = f.add(
                f"IFCOPENINGELEMENT({_s(ifc_guid(seed + ':void:' + oid))},$,{_s(oid)},"
                f"{_s(op.kind)},$,{local_placement},{shape(void_solid)},$,.OPENING.)"
            )
            f.add(
                f"IFCRELVOIDSELEMENT({_s(ifc_guid(seed + ':voidrel:' + oid))},$,$,$,"
                f"{wall},{void})"
            )
            if op.kind not in ("door", "window"):
                continue
            fill_solid = polygon_solid(rect_ring(a, b, w.thickness), height, base)
            entity = "IFCWINDOW" if is_window else "IFCDOOR"
            fill = f.add(
                f"{entity}({_s(ifc_guid(seed + ':fill:' + oid))},$,{_s(oid)},"
                f"{_s(op.symbol)},$,{local_placement},{shape(fill_solid)},$,"
                f"{_mm(height)},{_mm(op.width)},$,$,$)"
            )
            f.add(
                f"IFCRELFILLSELEMENT({_s(ifc_guid(seed + ':fillrel:' + oid))},$,$,$,"
                f"{void},{fill})"
            )
            contained.append(fill)

    if contained:
        f.add(
            f"IFCRELCONTAINEDINSPATIALSTRUCTURE({_s(ifc_guid(seed + ':contain'))},$,$,$,"
            f"({','.join(contained)}),{storey})"
        )

    header = (
        "ISO-10303-21;\n"
        "HEADER;\n"
        f"FILE_DESCRIPTION((\'ViewDefinition [CoordinationView]\'),\'2;1\');\n"
        f"FILE_NAME({_s(model.source + '.ifc')},'',(''),(''),"
        f"'roomgraph','roomgraph','');\n"
        "FILE_SCHEMA(('IFC4'));\n"
        "ENDSEC;\n"
        "DATA;\n"
    )
    return header + f.body() + "\nENDSEC;\nEND-ISO-10303-21;\n"


def write(model: PlanModel, path: str, opts: IfcOptions | None = None) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(export(model, opts))
