"""Structural grid: reference lines with lettered and numbered bubbles.

The first plan-scope symbol, and the reason that scope exists. A grid belongs
to no room -- its lines cross all of them, and its bubbles sit outside the
building entirely, where neither a room nor an opening context can reach.

What identifies it is the pairing: long lines spanning most of the drawing, at
a regular spacing, terminating in small circles that contain a single
character. Either half alone is weak; together nothing else looks like it.
"""

from __future__ import annotations

import math
import statistics

from ..geom import Pt, arc_span, dist, fit_circle, is_parallel
from . import Fixture, Match, PlanContext, Symbol

BUBBLE_DIAMETER = (300.0, 1200.0)
BUBBLE_RESIDUAL = 0.08
MIN_LINE_SPAN = 0.55        # of the drawing's extent along the line
MIN_LINES_PER_AXIS = 2
MIN_BUBBLES = 3
BUBBLE_REACH = 1500.0       # how far a bubble may sit from its line's end
MAX_SPACING_SPREAD = 0.45   # grids are regular, but bays do vary


def _bubbles(ctx: PlanContext) -> list[tuple[Pt, float, str | None]]:
    out: list[tuple[Pt, float, str | None]] = []
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
        near = ctx.text_near(centre, radius * 2.2)
        label = None
        for t in near:
            token = t.text.strip()
            if 1 <= len(token) <= 3 and (token.isalnum()):
                label = token
                break
        out.append((centre, radius, label))
    return out


def detect(ctx: PlanContext) -> Match | None:
    span_x, span_y = ctx.width, ctx.height
    if span_x <= 0 or span_y <= 0:
        return None

    bubbles = _bubbles(ctx)
    if len(bubbles) < MIN_BUBBLES:
        return None

    # A gridline is a long line that *ends at a bubble*. Length alone is not
    # enough -- an external wall is just as long, and without this the walls
    # join the sample and the bay spacing stops looking regular.
    axes: dict[str, list[float]] = {"x": [], "y": []}
    used: set[int] = set()
    for s in ctx.straight_strokes(min_length=MIN_LINE_SPAN * min(span_x, span_y)):
        vertical = is_parallel(s.vec, Pt(0.0, 1.0), tol_deg=3.0)
        horizontal = is_parallel(s.vec, Pt(1.0, 0.0), tol_deg=3.0)
        if not (vertical or horizontal):
            continue
        if vertical and s.length() < MIN_LINE_SPAN * span_y:
            continue
        if horizontal and s.length() < MIN_LINE_SPAN * span_x:
            continue
        anchor = None
        for i, (centre, radius, _label) in enumerate(bubbles):
            reach = max(BUBBLE_REACH, radius * 3.0)
            if min(dist(s.a, centre), dist(s.b, centre)) <= reach:
                anchor = i
                break
        if anchor is None:
            continue
        used.add(anchor)
        axes["x" if vertical else "y"].append(
            s.midpoint().x if vertical else s.midpoint().y
        )

    lines = 0
    spacings: list[float] = []
    for values in axes.values():
        distinct: list[float] = []
        for v in sorted(values):
            if not distinct or v - distinct[-1] > 200.0:
                distinct.append(v)
        if len(distinct) < MIN_LINES_PER_AXIS:
            continue
        lines += len(distinct)
        spacings.extend(
            b - a for a, b in zip(distinct, distinct[1:], strict=False) if b - a > 1.0
        )
    if lines < MIN_LINES_PER_AXIS * 2 or not spacings:
        return None

    attached = len(used)
    if attached < MIN_BUBBLES:
        return None

    mean = statistics.fmean(spacings)
    spread = statistics.pstdev(spacings) / mean if mean else 1.0
    if spread > MAX_SPACING_SPREAD:
        return None

    refs = sorted({bubbles[i][2] for i in used if bubbles[i][2]})
    conf = 0.70 + 0.10 * min(1.0, attached / 6.0) + (0.12 if refs else 0.0)
    return Match(
        kind="grid",
        confidence=min(0.94, conf),
        meta={
            "gridlines": lines,
            "bubbles": attached,
            "references": refs or None,
            "bay_mm": round(mean, 1),
            "bay_spread": round(spread, 3),
        },
    )


SYMBOL = Symbol(
    id="structural_grid",
    name="Structural grid",
    kind="grid",
    detect=detect,
    scope="plan",
    priority=10,
    description="Long reference lines at regular bays, ending in lettered bubbles.",
)


def _circle(centre, r, steps=24):
    return [
        (centre[0] + r * math.cos(2 * math.pi * i / steps),
         centre[1] + r * math.sin(2 * math.pi * i / steps))
        for i in range(steps + 1)
    ]


def _grid(cols=3, rows=3, bay=6000.0, extent=20000.0):
    strokes = []
    texts = []
    for i in range(cols):
        x = 2000.0 + bay * i
        strokes.append([(x, 500.0), (x, extent)])
        strokes.append(_circle((x, 0.0), 400.0))
        texts.append((chr(ord("A") + i), (x, 0.0)))
    for j in range(rows):
        y = 2000.0 + bay * j
        strokes.append([(500.0, y), (extent, y)])
        strokes.append(_circle((0.0, y), 400.0))
        texts.append((str(j + 1), (0.0, y)))
    return strokes, texts


_STROKES, _TEXTS = _grid()

FIXTURES = [
    Fixture(
        name="a 3 by 3 grid at 6 m bays with lettered bubbles",
        scope="plan",
        bounds=(-2000.0, -2000.0, 22000.0, 22000.0),
        strokes=_STROKES,
        placed_texts=_TEXTS,
        expect=True,
    ),
    Fixture(
        name="grid lines with no bubbles at all",
        scope="plan",
        bounds=(-2000.0, -2000.0, 22000.0, 22000.0),
        strokes=[s for s in _STROKES if len(s) == 2],
        expect=False,
    ),
    Fixture(
        name="bubbles with no grid lines",
        scope="plan",
        bounds=(-2000.0, -2000.0, 22000.0, 22000.0),
        strokes=[s for s in _STROKES if len(s) > 2],
        placed_texts=_TEXTS,
        expect=False,
    ),
    Fixture(
        name="lines in one direction only",
        scope="plan",
        bounds=(-2000.0, -2000.0, 22000.0, 22000.0),
        strokes=[s for s in _STROKES[:6]],
        placed_texts=_TEXTS[:3],
        expect=False,
    ),
    Fixture(
        name="an empty drawing",
        scope="plan",
        bounds=(0.0, 0.0, 20000.0, 20000.0),
        strokes=[],
        expect=False,
    ),
]
