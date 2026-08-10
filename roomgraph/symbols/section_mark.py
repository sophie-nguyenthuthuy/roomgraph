"""Section marks: a cut line with the same letter at both ends.

The paired letter is the whole signature. A single lettered bubble is a grid
reference; two bubbles carrying the *same* letter, at opposite ends of a line,
is a section -- and that pairing is also what tells you which line is the cut.

Reported with the letter and the cut's direction, because a consumer wanting to
match this plan to a section drawing needs both.
"""

from __future__ import annotations

import math

from ..geom import Pt, arc_span, dist, fit_circle
from . import Fixture, Match, PlanContext, Symbol, fold_text

BUBBLE_DIAMETER = (300.0, 1600.0)
BUBBLE_RESIDUAL = 0.08
MIN_SEPARATION = 2000.0
LABEL_REACH = 2.2
LINE_REACH = 1200.0


def _lettered_bubbles(ctx: PlanContext) -> list[tuple[Pt, str]]:
    out: list[tuple[Pt, str]] = []
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
        for t in ctx.text_near(centre, radius * LABEL_REACH):
            token = fold_text(t.text).strip()
            if len(token) == 1 and token.isalpha():
                out.append((centre, token.upper()))
                break
    return out


def detect(ctx: PlanContext) -> Match | None:
    bubbles = _lettered_bubbles(ctx)
    if len(bubbles) < 2:
        return None

    by_letter: dict[str, list[Pt]] = {}
    for centre, letter in bubbles:
        by_letter.setdefault(letter, []).append(centre)

    sections: list[dict] = []
    for letter, centres in sorted(by_letter.items()):
        if len(centres) != 2:
            continue   # three of a letter is a grid running A, B, C, not a cut
        a, b = centres
        separation = dist(a, b)
        if separation < MIN_SEPARATION:
            continue
        cut = None
        for s in ctx.straight_strokes(min_length=0.4 * separation):
            near_a = min(dist(s.a, a), dist(s.b, a))
            near_b = min(dist(s.a, b), dist(s.b, b))
            if near_a <= LINE_REACH and near_b <= LINE_REACH:
                cut = s
                break
        if cut is None:
            continue
        bearing = (90.0 - math.degrees(math.atan2(b.y - a.y, b.x - a.x))) % 360.0
        sections.append(
            {
                "label": f"{letter}-{letter}",
                "length_mm": round(separation, 1),
                "bearing_deg": round(bearing, 1),
            }
        )

    if not sections:
        return None
    conf = 0.74 + 0.08 * min(2, len(sections) - 1)
    return Match(
        kind="section_mark",
        confidence=min(0.90, conf),
        meta={"sections": sections, "count": len(sections)},
    )


SYMBOL = Symbol(
    id="section_mark",
    name="Section mark",
    kind="section_mark",
    detect=detect,
    scope="plan",
    priority=12,
    description="A cut line ending in two bubbles that carry the same letter.",
)


def _circle(centre, r=400.0, steps=24):
    return [
        (centre[0] + r * math.cos(2 * math.pi * i / steps),
         centre[1] + r * math.sin(2 * math.pi * i / steps))
        for i in range(steps + 1)
    ]


_SECTION = (
    [_circle((0.0, 0.0)), _circle((0.0, 12000.0)), [(0.0, 0.0), (0.0, 12000.0)]],
    [("A", (0.0, 0.0)), ("A", (0.0, 12000.0))],
)

FIXTURES = [
    Fixture(
        name="section A-A across the plan",
        scope="plan",
        strokes=_SECTION[0],
        placed_texts=_SECTION[1],
        expect=True,
    ),
    Fixture(
        name="two cuts, A-A and B-B",
        scope="plan",
        strokes=[
            *_SECTION[0],
            _circle((6000.0, 0.0)), _circle((6000.0, 12000.0)),
            [(6000.0, 0.0), (6000.0, 12000.0)],
        ],
        placed_texts=[*_SECTION[1], ("B", (6000.0, 0.0)), ("B", (6000.0, 12000.0))],
        expect=True,
    ),
    Fixture(
        name="a grid runs A, B, C: no letter is paired",
        scope="plan",
        strokes=[
            _circle((0.0, 0.0)), _circle((6000.0, 0.0)), _circle((12000.0, 0.0)),
            [(0.0, 0.0), (0.0, 12000.0)],
        ],
        placed_texts=[("A", (0.0, 0.0)), ("B", (6000.0, 0.0)), ("C", (12000.0, 0.0))],
        expect=False,
    ),
    Fixture(
        name="paired bubbles with no cut line between them",
        scope="plan",
        strokes=[_circle((0.0, 0.0)), _circle((0.0, 12000.0))],
        placed_texts=_SECTION[1],
        expect=False,
    ),
    Fixture(
        name="an empty drawing",
        scope="plan",
        strokes=[],
        expect=False,
    ),
]
