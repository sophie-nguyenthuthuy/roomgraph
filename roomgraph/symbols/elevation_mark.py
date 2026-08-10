"""Elevation marks: a bubble and an arrow pointing at a face.

Structurally the odd one out among the lettered bubbles. A grid reference sits
at the end of a long gridline; a section's bubble has a twin carrying the same
letter at the other end of a cut. An elevation mark has neither -- it is a lone
bubble with an arrow beside it, aimed at the elevation it names.

So it is identified by what it is *not* attached to, and the direction it aims
is reported, because that is what lets a consumer match this plan to the right
elevation drawing.
"""

from __future__ import annotations

import math

from ..geom import Pt, arc_span, dist, fit_circle, polygon_centroid
from . import Fixture, Match, PlanContext, Symbol, fold_text

BUBBLE_DIAMETER = (300.0, 1600.0)
BUBBLE_RESIDUAL = 0.08
ARROW_SIZE = (200.0, 3000.0)
ARROW_REACH = 3.0        # of the bubble radius
LONG_LINE = 6.0          # a line this many radii long makes it a gridline
LINE_REACH = 2.0


def detect(ctx: PlanContext) -> Match | None:
    bubbles: list[tuple[Pt, float, str]] = []
    for pts in ctx.strokes:
        if len(pts) < 8:
            continue
        fit = fit_circle(pts)
        if not fit:
            continue
        centre, radius, resid = fit
        if radius <= 0 or resid / radius > BUBBLE_RESIDUAL:
            continue
        if not (BUBBLE_DIAMETER[0] <= 2 * radius <= BUBBLE_DIAMETER[1]):
            continue
        if math.degrees(arc_span(pts, centre)) < 300.0:
            continue
        for t in ctx.text_near(centre, radius * 2.2):
            token = fold_text(t.text).strip()
            if 1 <= len(token) <= 2 and token.isalnum():
                bubbles.append((centre, radius, token.upper()))
                break

    if not bubbles:
        return None
    labels = [b[2] for b in bubbles]

    marks: list[dict] = []
    for centre, radius, label in bubbles:
        if labels.count(label) > 1:
            continue   # a twin makes it a section cut, not an elevation
        if any(
            s.length() >= LONG_LINE * radius
            and min(dist(s.a, centre), dist(s.b, centre)) <= LINE_REACH * radius
            for s in ctx.straight_strokes(min_length=LONG_LINE * radius)
        ):
            continue   # a long line makes it a grid reference

        arrow = None
        for pts in ctx.strokes:
            if not (3 <= len(pts) <= 6):
                continue
            size = max(dist(a, b) for a in pts for b in pts)
            if not (ARROW_SIZE[0] <= size <= ARROW_SIZE[1]):
                continue
            glyph = polygon_centroid(pts)
            if dist(glyph, centre) > ARROW_REACH * radius:
                continue
            apex = max(pts, key=lambda p: dist(p, glyph))
            arrow = apex - glyph
            break
        if arrow is None or arrow.norm() < 1e-6:
            continue
        bearing = (90.0 - math.degrees(math.atan2(arrow.y, arrow.x))) % 360.0
        marks.append({"label": label, "bearing_deg": round(bearing, 1)})

    if not marks:
        return None
    conf = 0.72 + 0.06 * min(3, len(marks) - 1)
    return Match(
        kind="elevation_mark",
        confidence=min(0.90, conf),
        meta={"marks": sorted(marks, key=lambda m: m["label"]), "count": len(marks)},
    )


SYMBOL = Symbol(
    id="elevation_mark",
    name="Elevation mark",
    kind="elevation_mark",
    detect=detect,
    scope="plan",
    priority=11,
    description="A lone lettered bubble with an arrow, attached to no gridline or cut.",
)


def _circle(centre, r=400.0, steps=24):
    return [
        (centre[0] + r * math.cos(2 * math.pi * i / steps),
         centre[1] + r * math.sin(2 * math.pi * i / steps))
        for i in range(steps + 1)
    ]


def _arrow(cx, cy, size=700.0, angle_deg=270.0):
    a = math.radians(angle_deg)
    return [
        (cx + size * math.cos(a), cy + size * math.sin(a)),
        (cx + 0.4 * size * math.cos(a + 2.4), cy + 0.4 * size * math.sin(a + 2.4)),
        (cx + 0.4 * size * math.cos(a - 2.4), cy + 0.4 * size * math.sin(a - 2.4)),
    ]


FIXTURES = [
    Fixture(
        name="elevation 1 aimed down the sheet",
        scope="plan",
        strokes=[_circle((0.0, 0.0)), _arrow(0.0, -700.0)],
        placed_texts=[("1", (0.0, 0.0))],
        expect=True,
    ),
    Fixture(
        name="two elevations aimed different ways",
        scope="plan",
        strokes=[
            _circle((0.0, 0.0)), _arrow(0.0, -700.0),
            _circle((9000.0, 0.0)), _arrow(9700.0, 0.0, angle_deg=0.0),
        ],
        placed_texts=[("1", (0.0, 0.0)), ("2", (9000.0, 0.0))],
        expect=True,
    ),
    Fixture(
        name="a section's paired bubbles are not elevations",
        scope="plan",
        strokes=[
            _circle((0.0, 0.0)), _arrow(0.0, -700.0),
            _circle((0.0, 9000.0)), _arrow(0.0, 9700.0, angle_deg=90.0),
        ],
        placed_texts=[("A", (0.0, 0.0)), ("A", (0.0, 9000.0))],
        expect=False,
    ),
    Fixture(
        name="a grid bubble sits at the end of a long line",
        scope="plan",
        strokes=[_circle((0.0, 0.0)), _arrow(0.0, -700.0), [(0.0, 0.0), (0.0, 18000.0)]],
        placed_texts=[("A", (0.0, 0.0))],
        expect=False,
    ),
    Fixture(
        name="a bubble with no arrow beside it",
        scope="plan",
        strokes=[_circle((0.0, 0.0))],
        placed_texts=[("1", (0.0, 0.0))],
        expect=False,
    ),
    Fixture(
        name="an empty drawing",
        scope="plan",
        strokes=[],
        expect=False,
    ),
]
