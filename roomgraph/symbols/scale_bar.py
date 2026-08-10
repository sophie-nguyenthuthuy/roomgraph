"""Scale bar: an independent check on the scale we inferred.

Everything downstream rests on millimetres-per-point, and that number is
recovered from dimension strings. A scale bar is a second, unrelated witness:
its divisions are drawn at a known length and labelled with it, so measuring
the bar and comparing against its own label either confirms the scale or says
plainly that something is wrong.

Reported either way, with the delta. This is the same cross-check the room
areas and the escape route get, and it is the cheapest of the three.
"""

from __future__ import annotations

import re
import statistics

from ..geom import Pt, oriented_extent, polygon_area
from . import Fixture, Match, PlanContext, Symbol

MIN_DIVISIONS = 3
DIVISION_ASPECT = 1.8          # a division is wider than it is tall
MAX_SIZE_SPREAD = 0.12
NUMBER = r"^\+?(\d{1,3}(?:[.,]\d)?)\s*(m|km|mm)?$"
LABEL_REACH = 4.0              # of the bar's height
TOLERANCE_PCT = 6.0


def detect(ctx: PlanContext) -> Match | None:
    boxes: list[tuple[Pt, float, float]] = []
    for loop in ctx.loops():
        area = abs(polygon_area(loop)) / 1e6
        if area <= 0:
            continue
        long_side, short_side = oriented_extent(loop)
        if short_side <= 0 or long_side / short_side < DIVISION_ASPECT:
            continue
        centre = Pt(
            sum(p.x for p in loop) / len(loop), sum(p.y for p in loop) / len(loop)
        )
        boxes.append((centre, long_side, short_side))
    if len(boxes) < MIN_DIVISIONS:
        return None

    for axis in (Pt(1.0, 0.0), Pt(0.0, 1.0)):
        run = _bar(boxes, axis)
        if run is None:
            continue
        divisions, length, height, centre = run
        stated = _stated(ctx, centre, height)
        if stated is None:
            continue
        measured = length / 1000.0
        delta = round(100.0 * (measured - stated) / stated, 2)
        conf = 0.72 + 0.10 * min(1.0, (divisions - MIN_DIVISIONS) / 4.0)
        conf += 0.10 if abs(delta) <= TOLERANCE_PCT else 0.0
        return Match(
            kind="scale_bar",
            confidence=min(0.92, conf),
            meta={
                "divisions": divisions,
                "measured_m": round(measured, 2),
                "stated_m": stated,
                "delta_pct": delta,
                "confirms_scale": abs(delta) <= TOLERANCE_PCT,
            },
        )
    return None


def _bar(boxes, axis: Pt):
    """The longest run of equal, abutting divisions along one axis.

    Grouped by genuine collinearity and matching height. Bucketing by each
    box's own height instead lets unrelated shapes share a bucket -- an extract
    canopy landing among the divisions is enough to fail the size check.
    """
    normal = axis.perp()
    best = None
    for seed_centre, _seed_long, seed_short in boxes:
        band = [
            (c, ln, h)
            for c, ln, h in boxes
            if abs(h - seed_short) <= 0.25 * seed_short
            and abs(c.dot(normal) - seed_centre.dot(normal)) <= 0.75 * seed_short
        ]
        if len(band) < MIN_DIVISIONS:
            continue
        lengths = [ln for _, ln, _ in band]
        mean_length = statistics.fmean(lengths)
        if statistics.pstdev(lengths) / mean_length > MAX_SIZE_SPREAD:
            continue
        positions = sorted(c.dot(axis) for c, _, _ in band)
        gaps = [b - a for a, b in zip(positions, positions[1:], strict=False)]
        # Divisions of a bar abut, so each step equals one division.
        if any(abs(g - mean_length) > 0.25 * mean_length for g in gaps):
            continue
        span = positions[-1] - positions[0] + mean_length
        height = statistics.fmean([h for _, _, h in band])
        mid = statistics.fmean(positions)
        across = statistics.fmean([c.dot(normal) for c, _, _ in band])
        centre = Pt(axis.x * mid + normal.x * across, axis.y * mid + normal.y * across)
        if best is None or len(band) > best[0]:
            best = (len(band), span, height, centre)
    return best


def _stated(ctx: PlanContext, centre: Pt, height: float) -> float | None:
    values: list[float] = []
    for t in ctx.text_near(centre, max(LABEL_REACH * height, 2000.0) * 4):
        m = re.fullmatch(NUMBER, t.text.strip())
        if not m:
            continue
        value = float(m.group(1).replace(",", "."))
        unit = (m.group(2) or "m").lower()
        if unit == "mm":
            value /= 1000.0
        elif unit == "km":
            value *= 1000.0
        values.append(value)
    positive = [v for v in values if v > 0]
    return max(positive) if positive else None


SYMBOL = Symbol(
    id="scale_bar",
    name="Scale bar",
    kind="scale_bar",
    detect=detect,
    scope="plan",
    priority=15,
    description="Equal graduated divisions, measured against their own label.",
)


def _division(x, y, w, h):
    return [(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)]


def _bar_at(x0=0.0, y0=0.0, division=2000.0, count=5, height=300.0):
    strokes = [_division(x0 + division * i, y0, division, height) for i in range(count)]
    texts = [("0", (x0, y0 - 400.0)), (str(int(division * count / 1000)),
             (x0 + division * count, y0 - 400.0))]
    return strokes, texts


_STROKES, _TEXTS = _bar_at()

FIXTURES = [
    Fixture(
        name="a 10 m bar in five divisions, labelled 10",
        scope="plan",
        strokes=_STROKES,
        placed_texts=_TEXTS,
        expect=True,
    ),
    Fixture(
        name="a bar whose label disagrees with its length",
        scope="plan",
        strokes=_STROKES,
        placed_texts=[("0", (0.0, -400.0)), ("25", (10000.0, -400.0))],
        expect=True,
        min_confidence=0.6,
    ),
    Fixture(
        name="divisions with no label at all",
        scope="plan",
        strokes=_STROKES,
        expect=False,
    ),
    Fixture(
        name="two divisions is not a bar",
        scope="plan",
        strokes=_STROKES[:2],
        placed_texts=_TEXTS,
        expect=False,
    ),
    Fixture(
        name="divisions of assorted lengths",
        scope="plan",
        strokes=[
            _division(0, 0, 2000, 300),
            _division(2000, 0, 3400, 300),
            _division(5400, 0, 1200, 300),
        ],
        placed_texts=_TEXTS,
        expect=False,
    ),
    Fixture(
        name="an empty drawing",
        scope="plan",
        strokes=[],
        expect=False,
    ),
]
