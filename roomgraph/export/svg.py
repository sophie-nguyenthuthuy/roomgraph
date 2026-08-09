"""Static SVG render: the plan, the rooms, and the graph drawn over them.

The graph layer is a real `<g>` you can toggle, so the same file works as a
figure in a README and as a debugging view when a room comes out wrong.
"""

from __future__ import annotations

from ..model import PlanModel
from .palette import BACKGROUND, EDGE_WALL, INK, MUTED, WALL, colour_for, hex_of, kind_colour

MARGIN_MM = 600.0


def _esc(s: str) -> str:
    return (
        s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def render(
    model: PlanModel,
    width_px: int = 1200,
    show_graph: bool = True,
    show_labels: bool = True,
) -> str:
    x0, y0, x1, y1 = model.bounds()
    x0 -= MARGIN_MM
    y0 -= MARGIN_MM
    x1 += MARGIN_MM
    y1 += MARGIN_MM
    w_mm = max(1.0, x1 - x0)
    h_mm = max(1.0, y1 - y0)
    height_px = int(round(width_px * h_mm / w_mm))
    scale = width_px / w_mm

    def X(x: float) -> float:
        return round((x - x0) * scale, 2)

    def Y(y: float) -> float:
        return round((y1 - y) * scale, 2)

    def mm(v: float) -> float:
        return round(v * scale, 2)

    out: list[str] = []
    out.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width_px} {height_px}" '
        f'width="{width_px}" height="{height_px}" font-family="ui-sans-serif, system-ui, sans-serif">'
    )
    out.append(f'<rect width="100%" height="100%" fill="{hex_of(BACKGROUND)}"/>')
    out.append(f"<title>{_esc(model.source)} - roomgraph</title>")

    # rooms
    out.append('<g id="rooms">')
    for r in model.rooms:
        pts = " ".join(f"{X(p.x)},{Y(p.y)}" for p in r.polygon)
        fill = hex_of(colour_for(r.category))
        out.append(
            f'<polygon points="{pts}" fill="{fill}" fill-opacity="0.55" '
            f'stroke="{fill}" stroke-width="1.5"><title>'
            f"{_esc(r.name or r.id)} - {r.area_gross_m2} m2 ({_esc(r.category)})"
            f"</title></polygon>"
        )
    out.append("</g>")

    # walls
    out.append(f'<g id="walls" stroke="{hex_of(WALL)}" stroke-linecap="butt">')
    for w in model.walls:
        out.append(
            f'<line x1="{X(w.a.x)}" y1="{Y(w.a.y)}" x2="{X(w.b.x)}" y2="{Y(w.b.y)}" '
            f'stroke-width="{max(1.2, mm(w.thickness))}"/>'
        )
    out.append("</g>")

    # openings, drawn over the wall so the gap reads as a gap
    out.append('<g id="openings" stroke-linecap="butt">')
    for op in model.openings:
        if not (0 <= op.wall < len(model.walls)):
            continue
        wall = model.walls[op.wall]
        a, b = wall.point_at_t(op.t_start), wall.point_at_t(op.t_end)
        out.append(
            f'<line x1="{X(a.x)}" y1="{Y(a.y)}" x2="{X(b.x)}" y2="{Y(b.y)}" '
            f'stroke="{hex_of(BACKGROUND)}" stroke-width="{max(1.2, mm(wall.thickness) + 1)}"/>'
        )
        out.append(
            f'<line x1="{X(a.x)}" y1="{Y(a.y)}" x2="{X(b.x)}" y2="{Y(b.y)}" '
            f'stroke="{hex_of(kind_colour(op.kind))}" stroke-width="{max(1.5, mm(wall.thickness) * 0.5)}">'
            f"<title>{_esc(model.opening_id(op))} {_esc(op.kind)} "
            f"{op.width:.0f} mm ({_esc(op.symbol or 'unmatched')}, conf {op.confidence})</title></line>"
        )
    out.append("</g>")

    if show_graph:
        out.append('<g id="graph">')
        for e in model.graph.edges:
            ra = next((r for r in model.rooms if r.id == e.a), None)
            rb = next((r for r in model.rooms if r.id == e.b), None)
            if not ra or not rb:
                continue
            colour = hex_of(EDGE_WALL if e.kind == "wall" else kind_colour(e.kind))
            dash = ' stroke-dasharray="6 5"' if e.kind == "wall" else ""
            out.append(
                f'<line x1="{X(ra.label_point.x)}" y1="{Y(ra.label_point.y)}" '
                f'x2="{X(rb.label_point.x)}" y2="{Y(rb.label_point.y)}" '
                f'stroke="{colour}" stroke-width="{3 if e.kind != "wall" else 2}"{dash}>'
                f"<title>{_esc(e.a)} - {_esc(e.b)}: {_esc(e.kind)}</title></line>"
            )
        for r in model.rooms:
            out.append(
                f'<circle cx="{X(r.label_point.x)}" cy="{Y(r.label_point.y)}" r="9" '
                f'fill="{hex_of(colour_for(r.category))}" stroke="{hex_of(BACKGROUND)}" '
                f'stroke-width="3"/>'
            )
        out.append("</g>")

    if show_labels:
        out.append(f'<g id="labels" text-anchor="middle" fill="{hex_of(INK)}">')
        for r in model.rooms:
            cx, cy = X(r.label_point.x), Y(r.label_point.y)
            name = _esc(r.name or r.id)
            out.append(
                f'<text x="{cx}" y="{cy - 16}" font-size="15" font-weight="600" '
                f'paint-order="stroke" stroke="{hex_of(BACKGROUND)}" stroke-width="4">{name}</text>'
            )
            out.append(
                f'<text x="{cx}" y="{cy + 30}" font-size="13" fill="{hex_of(MUTED)}" '
                f'paint-order="stroke" stroke="{hex_of(BACKGROUND)}" stroke-width="4">'
                f"{r.area_gross_m2:.1f} m²</text>"
            )
        out.append("</g>")

    footer = (
        f"{len(model.rooms)} rooms · {model.total_area_m2:.1f} m² · "
        f"scale {model.scale.to_dict()['drawing_scale']} ({model.scale.source})"
    )
    out.append(
        f'<text x="12" y="{height_px - 12}" font-size="13" fill="{hex_of(MUTED)}">{_esc(footer)}</text>'
    )
    out.append("</svg>")
    return "\n".join(out)


def write(model: PlanModel, path: str, **kwargs) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(render(model, **kwargs))
        fh.write("\n")
