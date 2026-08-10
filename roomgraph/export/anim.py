"""The GIF: a plan dissolving into a coloured room graph.

Five beats, and the order is the argument the project is making --

  1. the drawing arrives as anonymous lines
  2. walls resolve into walls (thickness recovered)
  3. rooms flood with colour (faces found, areas measured)
  4. the plan dissolves away
  5. the graph is what is left

Each beat is a function of one eased parameter, so retiming means changing a
number of frames, not the drawing code.
"""

from __future__ import annotations

from ..geom import Pt
from ..model import PlanModel
from .palette import (
    BACKGROUND,
    DOOR,
    EDGE_WALL,
    INK,
    MUTED,
    WALL,
    colour_for,
    kind_colour,
    material_colour,
)
from .raster import Canvas, mix, write_gif


def _ease(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


class _View:
    """Millimetres to pixels, y flipped."""

    def __init__(self, model: PlanModel, w: int, h: int, pad: int = 46) -> None:
        x0, y0, x1, y1 = model.bounds()
        span_x = max(1.0, x1 - x0)
        span_y = max(1.0, y1 - y0)
        self.k = min((w - 2 * pad) / span_x, (h - 2 * pad - 34) / span_y)
        self.ox = (w - span_x * self.k) / 2.0 - x0 * self.k
        self.oy = (h - 34 - span_y * self.k) / 2.0 - y0 * self.k
        self.h = h

    def x(self, v: float) -> float:
        return v * self.k + self.ox

    def y(self, v: float) -> float:
        return self.h - (v * self.k + self.oy)

    def px(self, p: Pt) -> tuple[float, float]:
        return (self.x(p.x), self.y(p.y))

    def mm(self, v: float) -> float:
        return v * self.k


def _draw_walls(c: Canvas, model: PlanModel, view: _View, colour, thin: float) -> None:
    for w in model.walls:
        ax, ay = view.px(w.a)
        bx, by = view.px(w.b)
        width = max(1.0, view.mm(w.thickness) * thin + (1.0 - thin) * 1.4)
        c.thick_line(ax, ay, bx, by, width, colour, round_caps=False)


def _hatch_regions(model: PlanModel) -> list[dict]:
    for feature in model.plan_features:
        if feature.symbol == "hatch_pattern":
            return feature.meta.get("regions", [])
    return []


def _hatch_rulings(model: PlanModel) -> list[tuple[str | None, list]]:
    """The rulings the detector actually grouped, not a bounding box.

    A box catches whatever else falls inside it -- door swings, wall faces --
    and paints geometry the hatch never contained.
    """
    if model.geometry is None or not _hatch_regions(model):
        return []
    from ..openings import build_plan_context
    from ..symbols.hatch_pattern import region_rulings

    ctx = build_plan_context(model.geometry, model.scale.mm_per_pt, model.rooms)
    return region_rulings(ctx)


def _draw_hatch(c: Canvas, model: PlanModel, view: _View, strength: float, cache=None) -> None:
    for index, (_material, group) in enumerate(cache or []):
        colour = mix(BACKGROUND, material_colour(index), strength)
        for seg in group:
            ax, ay = view.px(seg.a)
            bx, by = view.px(seg.b)
            c.aa_line(ax, ay, bx, by, colour, 1.5)


def _draw_openings(c: Canvas, model: PlanModel, view: _View, strength: float) -> None:
    for op in model.openings:
        if not (0 <= op.wall < len(model.walls)):
            continue
        wall = model.walls[op.wall]
        a = view.px(wall.point_at_t(op.t_start))
        b = view.px(wall.point_at_t(op.t_end))
        gap = max(1.0, view.mm(wall.thickness) + 2)
        c.thick_line(a[0], a[1], b[0], b[1], gap, BACKGROUND, round_caps=False)
        col = mix(BACKGROUND, kind_colour(op.kind), strength)
        c.thick_line(a[0], a[1], b[0], b[1], max(2.0, gap * 0.55), col, round_caps=False)


def _draw_rooms(c: Canvas, model: PlanModel, view: _View, strength: float, shrink: float = 0.0) -> None:
    for r in model.rooms:
        base = colour_for(r.category)
        col = mix(BACKGROUND, base, strength)
        anchor = r.label_point
        pts = []
        for p in r.polygon:
            q = Pt(
                p.x + (anchor.x - p.x) * shrink,
                p.y + (anchor.y - p.y) * shrink,
            )
            pts.append(view.px(q))
        c.fill_polygon(pts, col)


def _draw_graph(c: Canvas, model: PlanModel, view: _View, strength: float, node_scale: float) -> None:
    by_id = {r.id: r for r in model.rooms}
    for e in model.graph.edges:
        ra, rb = by_id.get(e.a), by_id.get(e.b)
        if not ra or not rb:
            continue
        base = EDGE_WALL if e.kind == "wall" else kind_colour(e.kind)
        col = mix(BACKGROUND, base, strength)
        ax, ay = view.px(ra.label_point)
        bx, by = view.px(rb.label_point)
        if e.kind == "wall":
            steps = 26
            for i in range(0, steps, 2):
                t0, t1 = i / steps, min(1.0, (i + 1) / steps)
                c.aa_line(
                    ax + (bx - ax) * t0, ay + (by - ay) * t0,
                    ax + (bx - ax) * t1, ay + (by - ay) * t1,
                    col, 2.0,
                )
        else:
            c.aa_line(ax, ay, bx, by, col, 3.4)

    for e in model.graph.entrances:
        ra = by_id.get(e.a)
        if not ra or e.point is None:
            continue
        ax, ay = view.px(ra.label_point)
        bx, by = view.px(e.point)
        c.aa_line(ax, ay, bx, by, mix(BACKGROUND, DOOR, strength * 0.8), 2.4)
        c.fill_circle(bx, by, 5 * node_scale, mix(BACKGROUND, DOOR, strength))

    for r in model.rooms:
        cx, cy = view.px(r.label_point)
        rad = 13 * node_scale
        c.fill_circle(cx, cy, rad + 3, mix(BACKGROUND, (255, 255, 255), strength))
        c.fill_circle(cx, cy, rad, mix(BACKGROUND, colour_for(r.category), strength))


def _caption(c: Canvas, text: str, sub: str, strength: float) -> None:
    col = mix(BACKGROUND, INK, strength)
    sub_col = mix(BACKGROUND, MUTED, strength)
    c.text(text, 16, c.h - 30, col, scale=2)
    if sub:
        c.text(sub, 16, c.h - 14, sub_col, scale=1)


def storyboard(
    model: PlanModel,
    width: int = 760,
    height: int = 560,
    hold: int = 10,
    beat: int = 14,
) -> tuple[list[Canvas], list[int]]:
    view = _View(model, width, height)
    frames: list[Canvas] = []
    delays: list[int] = []

    scale_note = (
        f"SCALE {model.scale.to_dict()['drawing_scale']} FROM {model.scale.source.upper()}"
    )
    total = f"{len(model.rooms)} ROOMS  {model.total_area_m2:.1f} M2"

    def new() -> Canvas:
        c = Canvas(width, height, BACKGROUND)
        return c

    # 1 - lines only
    for _ in range(hold):
        c = new()
        _draw_walls(c, model, view, mix(BACKGROUND, MUTED, 0.75), 0.0)
        _caption(c, "VECTOR PDF", "LINES, NO STRUCTURE", 1.0)
        frames.append(c)
        delays.append(6)

    # 2 - walls gain thickness
    for i in range(beat):
        t = _ease(i / max(1, beat - 1))
        c = new()
        _draw_walls(c, model, view, mix(mix(BACKGROUND, MUTED, 0.75), WALL, t), t)
        _draw_openings(c, model, view, t)
        _caption(c, "WALLS", f"{len(model.walls)} PAIRED FACES, {len(model.openings)} OPENINGS", 1.0)
        frames.append(c)
        delays.append(5)

    # 3 - materials, where the drawing named them
    regions = _hatch_regions(model)
    rulings = _hatch_rulings(model)
    if regions and rulings:
        named = [r["material"] for r in regions if r.get("material")]
        caption = ", ".join(dict.fromkeys(named))[:44] or f"{len(regions)} REGIONS"
        for i in range(beat + hold):
            t = _ease(min(1.0, i / max(1, beat - 1)))
            c = new()
            # Walls thin here so the rulings inside them are visible: a solid
            # wall bar hides the very thing this beat is about.
            _draw_walls(c, model, view, mix(BACKGROUND, WALL, 0.35), 0.0)
            _draw_hatch(c, model, view, t, rulings)
            _caption(c, "MATERIALS", caption.upper(), 1.0)
            frames.append(c)
            delays.append(5 if i < beat else 7)

    # 4 - rooms flood with colour
    for i in range(beat):
        t = _ease(i / max(1, beat - 1))
        c = new()
        _draw_rooms(c, model, view, t)
        _draw_hatch(c, model, view, 1.0 - t, rulings)
        _draw_walls(c, model, view, WALL, 1.0)
        _draw_openings(c, model, view, 1.0)
        _caption(c, "ROOMS", f"{total}  {scale_note}", 1.0)
        frames.append(c)
        delays.append(5)

    for _ in range(hold):
        c = new()
        _draw_rooms(c, model, view, 1.0)
        _draw_walls(c, model, view, WALL, 1.0)
        _draw_openings(c, model, view, 1.0)
        _caption(c, "ROOMS", f"{total}  {scale_note}", 1.0)
        frames.append(c)
        delays.append(7)

    # 5 - the plan dissolves, rooms contract toward their nodes
    for i in range(beat + 4):
        t = _ease(i / max(1, beat + 3))
        c = new()
        _draw_rooms(c, model, view, 1.0 - 0.55 * t, shrink=t * 0.94)
        _draw_walls(c, model, view, mix(WALL, BACKGROUND, t), 1.0 - 0.85 * t)
        if t < 0.6:
            _draw_openings(c, model, view, 1.0 - t / 0.6)
        _draw_graph(c, model, view, t, 0.35 + 0.65 * t)
        _caption(c, "ROOM GRAPH", "ADJACENCY VIA DOORS AND OPENINGS", 1.0)
        frames.append(c)
        delays.append(5)

    # 6 - the graph, alone
    doors = sum(1 for e in model.graph.edges if e.kind != "wall")
    for _ in range(hold + 8):
        c = new()
        _draw_graph(c, model, view, 1.0, 1.0)
        for r in model.rooms:
            cx, cy = view.px(r.label_point)
            label = (r.name or r.id)[:14]
            c.text(label, cx - c.text_width(label, 1) / 2, cy + 20, INK, scale=1)
        _caption(c, "ROOM GRAPH", f"{len(model.rooms)} NODES  {doors} WALKABLE EDGES", 1.0)
        frames.append(c)
        delays.append(7)

    return frames, delays


def write(model: PlanModel, path: str, width: int = 760, height: int = 560) -> int:
    frames, delays = storyboard(model, width=width, height=height)
    write_gif(path, frames, delays)
    return len(frames)
