"""Hatch legend: the key that says what the fills mean.

A column of swatches, each with a caption to its right, under a title. Reading
it gives the drawing's material vocabulary -- brickwork, blockwork, insulation,
screed -- which is the vocabulary any later hatch-recognition work would have
to be written against.

The hatch patterns themselves are not identified. That is the next piece of
work, and this is the piece that tells you what to look for.
"""

from __future__ import annotations

import re
import statistics

from ..geom import Pt, dist, oriented_extent, polygon_area
from . import Fixture, Match, PlanContext, Symbol, fold_text

TITLE = r"\b(legend|key|hatch\s*legend|chu\s*thich|ghi\s*chu\s*vat\s*lieu)\b"
SWATCH_SIZE = (150.0, 1600.0)
MAX_ASPECT = 3.0
MIN_ENTRIES = 2
CAPTION_REACH = 6.0          # of the swatch width
COLUMN_TOL = 1.5             # how far swatches may stray from a shared column
COLUMN_REACH = 20.0          # how far the column may run from its title
MAX_ROW_SPREAD = 0.30


def detect(ctx: PlanContext) -> Match | None:
    title = None
    title_at = None
    for t in ctx.texts:
        if re.search(TITLE, fold_text(t.text)):
            title, title_at = t.text.strip(), t.at
            break
    if title is None or title_at is None:
        return None

    swatches: list[tuple[Pt, float]] = []
    for loop in ctx.loops():
        if abs(polygon_area(loop)) / 1e6 <= 0:
            continue
        long_side, short_side = oriented_extent(loop)
        if short_side <= 0 or long_side / short_side > MAX_ASPECT:
            continue
        if not (SWATCH_SIZE[0] <= long_side <= SWATCH_SIZE[1]):
            continue
        centre = Pt(
            sum(p.x for p in loop) / len(loop), sum(p.y for p in loop) / len(loop)
        )
        swatches.append((centre, long_side))
    if len(swatches) < MIN_ENTRIES:
        return None

    # A legend is a column beneath its title. Without that, any small square
    # anywhere on the sheet joins in -- an elevation arrowhead, a swatch-sized
    # anything -- and the captions come back as whatever text sat nearest.
    column: list[tuple[Pt, float]] = []
    for seed_centre, seed_size in swatches:
        if dist(seed_centre, title_at) > COLUMN_REACH * seed_size:
            continue
        if seed_centre.y >= title_at.y:
            continue
        group = [
            (c, sz) for c, sz in swatches
            if abs(c.x - seed_centre.x) <= COLUMN_TOL * seed_size
            and dist(c, title_at) <= COLUMN_REACH * seed_size
            and c.y < title_at.y      # a legend reads downward from its title
        ]
        if len(group) > len(column):
            column = group
    swatches = column
    if len(swatches) < MIN_ENTRIES:
        return None

    entries: list[str] = []
    for centre, size in sorted(swatches, key=lambda s: -s[0].y):
        captions = [
            t for t in ctx.text_near(centre, CAPTION_REACH * size)
            if t.at.x > centre.x and not re.search(TITLE, fold_text(t.text))
        ]
        if not captions:
            continue
        nearest = min(captions, key=lambda t: abs(t.at.y - centre.y))
        entries.append(nearest.text.strip())
    if len(entries) < MIN_ENTRIES:
        return None

    rows = sorted(c.y for c, _ in swatches)
    gaps = [b - a for a, b in zip(rows, rows[1:], strict=False) if b - a > 1.0]
    spread = (
        statistics.pstdev(gaps) / statistics.fmean(gaps) if len(gaps) > 1 else 0.0
    )
    conf = 0.72 + 0.08 * min(2, len(entries) - MIN_ENTRIES)
    conf += 0.08 if spread <= MAX_ROW_SPREAD else 0.0
    return Match(
        kind="hatch_legend",
        confidence=min(0.90, conf),
        meta={"title": title, "entries": entries, "count": len(entries)},
    )


SYMBOL = Symbol(
    id="hatch_legend",
    name="Hatch legend",
    kind="hatch_legend",
    detect=detect,
    scope="plan",
    priority=10,
    description="A column of swatches with captions, under a legend title.",
)


def _swatch(x, y, size=600.0):
    return [(x, y), (x + size, y), (x + size, y + size), (x, y + size), (x, y)]


_ENTRIES = ("BRICKWORK", "BLOCKWORK", "INSULATION")
_STROKES = [_swatch(0.0, -1200.0 * i) for i in range(len(_ENTRIES))]
_TEXTS = [("LEGEND", (0.0, 1200.0))] + [
    (name, (900.0, -1200.0 * i + 300.0)) for i, name in enumerate(_ENTRIES)
]

FIXTURES = [
    Fixture(
        name="three captioned swatches under a legend title",
        scope="plan",
        strokes=_STROKES,
        placed_texts=_TEXTS,
        expect=True,
    ),
    Fixture(
        name="a Vietnamese legend",
        scope="plan",
        strokes=_STROKES[:2],
        placed_texts=[("CHÚ THÍCH", (0.0, 1200.0)), ("GACH", (900.0, 300.0)),
                      ("BE TONG", (900.0, -900.0))],
        expect=True,
    ),
    Fixture(
        name="swatches with no legend title",
        scope="plan",
        strokes=_STROKES,
        placed_texts=_TEXTS[1:],
        expect=False,
    ),
    Fixture(
        name="a legend title with no swatches",
        scope="plan",
        strokes=[],
        placed_texts=_TEXTS,
        expect=False,
    ),
    Fixture(
        name="swatches with no captions beside them",
        scope="plan",
        strokes=_STROKES,
        placed_texts=[("LEGEND", (0.0, 1200.0))],
        expect=False,
    ),
    Fixture(
        name="an empty drawing",
        scope="plan",
        strokes=[],
        expect=False,
    ),
]
