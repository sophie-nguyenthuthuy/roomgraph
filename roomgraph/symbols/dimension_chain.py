"""Setting-out dimensions: a chain, and whether it adds up.

A dimension run is drawn as collinear segments, each labelled with the distance
it spans. That gives a check the drawing performs on itself: the parts of a
chain should sum to the whole it covers, and where they do not, either the
drawing is wrong or we have misread it.

Reported with the discrepancy either way. This is the same shape of test as the
room areas, the scale bar and the travel distance -- and the fourth independent
way to notice that the scale is wrong.
"""

from __future__ import annotations

import math
import re

from ..geom import Seg, angle_of, is_parallel, point_seg_distance, project_param
from . import Fixture, Match, PlanContext, Symbol

VALUE = r"^[^\d]{0,2}(\d{3,6})(?:\s*mm)?[^\d]{0,2}$"
VALUE_RANGE = (200.0, 100000.0)
LABEL_REACH = 6.0            # multiple of the text height, or an absolute floor
MIN_LINKS = 2
COLLINEAR_TOL = 400.0
TOLERANCE_PCT = 2.0


def _links(ctx: PlanContext) -> list[tuple[Seg, float]]:
    """Dimension segments paired with the value written beside them."""
    segs = ctx.straight_strokes(min_length=200.0)
    if not segs:
        return []
    out: list[tuple[Seg, float]] = []
    for t in ctx.texts:
        m = re.match(VALUE, t.text.strip())
        if not m:
            continue
        value = float(m.group(1))
        if not (VALUE_RANGE[0] <= value <= VALUE_RANGE[1]):
            continue
        reach = max(LABEL_REACH * t.height, 1200.0)
        best: tuple[float, Seg] | None = None
        for s in segs:
            # Deliberately no "value must match the segment length" filter.
            # Pairing on that basis would make the sum check tautological: it
            # could only ever confirm what it had already assumed. Text is
            # matched to the nearest segment it sits alongside, and the
            # arithmetic is then allowed to disagree.
            d = point_seg_distance(t.at, s)
            if d > reach:
                continue
            tt = project_param(t.at, s)
            if not (0.0 <= tt <= 1.0):
                continue
            if best is None or d < best[0]:
                best = (d, s)
        if best:
            out.append((best[1], value))
    return out


def detect(ctx: PlanContext) -> Match | None:
    links = _links(ctx)
    if len(links) < MIN_LINKS:
        return None

    chains: list[list[tuple[Seg, float]]] = []
    for seg, value in links:
        for chain in chains:
            ref = chain[0][0]
            if not is_parallel(ref.vec, seg.vec, tol_deg=3.0):
                continue
            normal = ref.dir().perp()
            if abs((seg.a - ref.a).dot(normal)) > COLLINEAR_TOL:
                continue
            chain.append((seg, value))
            break
        else:
            chains.append([(seg, value)])

    best: Match | None = None
    for chain in chains:
        if len(chain) < MIN_LINKS:
            continue
        d = chain[0][0].dir()
        starts = [min(s.a.dot(d), s.b.dot(d)) for s, _ in chain]
        ends = [max(s.a.dot(d), s.b.dot(d)) for s, _ in chain]
        span = max(ends) - min(starts)
        total = sum(v for _, v in chain)
        if span <= 0:
            continue
        delta = round(100.0 * (total - span) / span, 2)
        bearing = round(math.degrees(angle_of(d)) % 180.0, 1)
        conf = 0.70 + 0.08 * min(2, len(chain) - MIN_LINKS)
        conf += 0.10 if abs(delta) <= TOLERANCE_PCT else 0.0
        match = Match(
            kind="dimension_chain",
            confidence=min(0.92, conf),
            meta={
                "links": len(chain),
                "stated_mm": round(total, 1),
                "measured_mm": round(span, 1),
                "delta_pct": delta,
                "adds_up": abs(delta) <= TOLERANCE_PCT,
                "bearing_deg": bearing,
                "values_mm": sorted(round(v, 1) for _, v in chain),
            },
        )
        if best is None or match.confidence > best.confidence:
            best = match
    return best


SYMBOL = Symbol(
    id="dimension_chain",
    name="Setting-out dimensions",
    kind="dimension_chain",
    detect=detect,
    scope="plan",
    priority=10,
    description="A run of collinear dimensions, checked against the span they cover.",
)


def _chain(values, y=0.0, x0=0.0):
    strokes, texts = [], []
    x = x0
    for v in values:
        strokes.append([(x, y), (x + v, y)])
        texts.append((str(int(v)), (x + v / 2.0, y + 200.0)))
        x += v
    return strokes, texts


_STROKES, _TEXTS = _chain([6000.0, 4800.0, 6000.0])

FIXTURES = [
    Fixture(
        name="a chain of three that adds up",
        scope="plan",
        strokes=_STROKES,
        placed_texts=_TEXTS,
        expect=True,
    ),
    Fixture(
        name="a chain whose parts do not sum to the whole",
        scope="plan",
        strokes=_STROKES,
        placed_texts=[("6000", (3000.0, 200.0)), ("4800", (8400.0, 200.0)),
                      ("9000", (13800.0, 200.0))],
        expect=True,
        min_confidence=0.6,
    ),
    Fixture(
        name="a single dimension is not a chain",
        scope="plan",
        strokes=_STROKES[:1],
        placed_texts=_TEXTS[:1],
        expect=False,
    ),
    Fixture(
        name="dimensions at right angles are separate runs",
        scope="plan",
        strokes=[[(0.0, 0.0), (6000.0, 0.0)], [(0.0, 0.0), (0.0, 4800.0)]],
        placed_texts=[("6000", (3000.0, 200.0)), ("4800", (200.0, 2400.0))],
        expect=False,
    ),
    Fixture(
        name="an empty drawing",
        scope="plan",
        strokes=[],
        expect=False,
    ),
]
