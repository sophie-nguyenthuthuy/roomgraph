"""Travelator: a moving walkway -- an escalator's run without the rise.

Geometrically a travelator and an escalator are the same drawing: pallets
between two balustrades. What differs is length, and what settles it is the
label. A single escalator flight spans one storey and rarely exceeds twelve
metres; a travelator runs as far as the building does.

So this claims the geometry only when the drawing names it, or when the run is
longer than any escalator would be. Otherwise `escalator` keeps it, which is
the better wrong answer of the two -- both are a powered incline, and the rise
is the part a plan cannot show.
"""

from __future__ import annotations

import statistics

from ..geom import Pt, Seg, is_parallel
from . import Fixture, Match, RoomContext, Symbol

WORDS = r"\b(travelator|travolator|moving\s*walk\w*|walkway|bang\s*chuyen)\b"
LONGER_THAN_ANY_ESCALATOR = 16000.0
MIN_RUN = 6000.0
BAND_WIDTH = (800.0, 2200.0)
PALLET_SPACING = (250.0, 900.0)
MAX_SPACING_SPREAD = 0.30
RAIL_COVERAGE = 0.75


def detect(ctx: RoomContext) -> Match | None:
    named = ctx.text_matches(WORDS)
    segs = ctx.straight_strokes(min_length=200.0)
    if len(segs) < 2:
        return None  # two balustrades is the minimum; pallets are optional

    best: Match | None = None
    for i, a in enumerate(segs):
        if a.length() < MIN_RUN:
            continue
        n = a.dir().perp()
        for b in segs[i + 1:]:
            if b.length() < MIN_RUN or not is_parallel(a.vec, b.vec, tol_deg=6.0):
                continue
            offset = (b.a - a.a).dot(n)   # signed: the interior test needs the side
            gap = abs(offset)
            if not (BAND_WIDTH[0] <= gap <= BAND_WIDTH[1]):
                continue
            run = min(a.length(), b.length())
            if run < RAIL_COVERAGE * max(a.length(), b.length()):
                continue
            if not named and run < LONGER_THAN_ANY_ESCALATOR:
                continue  # too short to claim over an escalator without a label

            pallets = _pallets(ctx, a, b, n, offset)
            if not named and not pallets:
                # Two long parallel lines with nothing between them are a
                # corridor, an escape route beside a wall, anything at all.
                continue
            conf = 0.80 if named else 0.72
            conf += 0.08 if pallets else 0.0
            conf += 0.07 * min(1.0, run / 30000.0)
            match = Match(
                kind="travelator",
                confidence=min(0.95, conf),
                meta={
                    "run_mm": round(run, 1),
                    "width_mm": round(gap, 1),
                    "pallets": pallets,
                    "label": (named or "").strip() or None,
                },
            )
            if best is None or match.confidence > best.confidence:
                best = match
    return best


def _pallets(ctx: RoomContext, side: Seg, other: Seg, normal: Pt, offset: float) -> int:
    """Evenly spaced pallet joints lying *between* the two balustrades.

    The interior test is what makes this usable. Without it a single wall
    fragment elsewhere in the room joins the sample, and one stray spacing is
    enough to push the run's regularity past the threshold.
    """
    gap = abs(offset)
    d = side.dir()
    lo = min(side.a.dot(d), side.b.dot(d), other.a.dot(d), other.b.dot(d))
    hi = max(side.a.dot(d), side.b.dot(d), other.a.dot(d), other.b.dot(d))

    crossers = []
    for s in ctx.straight_strokes(min_length=0.6 * gap):
        if not is_parallel(s.vec, normal, tol_deg=12.0) or s.length() > 1.4 * gap:
            continue
        mid = s.midpoint()
        across = (mid - side.a).dot(normal)
        if not (min(0.0, offset) - 1.0 <= across <= max(0.0, offset) + 1.0):
            continue
        if not (lo - 1.0 <= mid.dot(d) <= hi + 1.0):
            continue
        crossers.append(s)
    if len(crossers) < 4:
        return 0
    offsets = sorted(s.midpoint().dot(d) for s in crossers)
    gaps = [q - p for p, q in zip(offsets, offsets[1:], strict=False) if q - p > 1.0]
    if len(gaps) < 3:
        return 0
    mean = statistics.fmean(gaps)
    if not (PALLET_SPACING[0] <= mean <= PALLET_SPACING[1]):
        return 0
    if statistics.pstdev(gaps) / mean > MAX_SPACING_SPREAD:
        return 0
    return len(crossers)


SYMBOL = Symbol(
    id="travelator",
    name="Travelator",
    kind="travelator",
    detect=detect,
    scope="room",
    priority=35,
    description="A long walkway band, named as one or longer than any escalator.",
)


_HALL = [(0, 0), (8000, 0), (8000, 40000), (0, 40000)]


def _band(x, y, width, length, pallets=0):
    out = [[(x, y), (x, y + length)], [(x + width, y), (x + width, y + length)]]
    for i in range(pallets):
        py = y + length * i / max(1, pallets - 1)
        out.append([(x, py), (x + width, py)])
    return out


FIXTURES = [
    Fixture(
        name="a 30 m band labelled as a travelator",
        polygon=_HALL,
        texts=["TRAVELATOR"],
        strokes=_band(1000, 1000, 1400, 30000, pallets=40),
        expect=True,
    ),
    Fixture(
        name="a Vietnamese label",
        polygon=_HALL,
        texts=["BĂNG CHUYỀN"],
        strokes=_band(1000, 1000, 1200, 12000),
        expect=True,
    ),
    Fixture(
        name="unlabelled, but far longer than any escalator",
        polygon=_HALL,
        strokes=_band(1000, 1000, 1400, 24000, pallets=30),
        expect=True,
    ),
    Fixture(
        name="an unlabelled 9 m band belongs to the escalator",
        polygon=_HALL,
        strokes=_band(1000, 1000, 1200, 9000, pallets=24),
        expect=False,
    ),
    Fixture(
        name="a label with no band drawn",
        polygon=_HALL,
        texts=["TRAVELATOR"],
        strokes=[],
        expect=False,
    ),
    Fixture(
        name="an empty hall",
        polygon=_HALL,
        strokes=[],
        expect=False,
    ),
]
