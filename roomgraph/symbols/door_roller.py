"""Roller shutter: a slatted curtain that winds onto a barrel.

Two conventions, either of which is enough:

  * the curtain drawn as a fine corrugation -- many small equal teeth along the
    opening, standing for the slats
  * a plain curtain line plus the barrel, a small circle at one jamb whose
    radius is a fraction of the opening

A shutter drawn as a bare line with no barrel and no corrugation is *not*
claimed: at that point the drawing contains nothing that distinguishes it from
a sliding leaf, and it falls back to `door_sliding`.
"""

from __future__ import annotations

import math

from ..geom import Seg, dist
from . import Fixture, Match, OpeningContext, Symbol, along_wall, coverage_of

MIN_TEETH = 8
MAX_TOOTH = 0.14          # tooth length as a fraction of the opening
MIN_CORRUGATION_SPAN = 0.7
BARREL_RADIUS = (60.0, 450.0)
BARREL_MAX_RATIO = 0.30   # barrel radius against the opening width
BARREL_NEAR_JAMB = 0.30
MIN_CURTAIN_COVERAGE = 0.6

# A barrel or a corrugation is unambiguous, so this floor sits above the
# sliding-door ceiling: both symbols see the same curtain line.
BASE_CONFIDENCE = 0.91


def _teeth(ctx: OpeningContext) -> list[Seg]:
    limit = MAX_TOOTH * ctx.width
    out: list[Seg] = []
    for pts in ctx.strokes:
        for i in range(len(pts) - 1):
            d = dist(pts[i], pts[i + 1])
            if 1.0 < d <= limit:
                out.append(Seg(pts[i], pts[i + 1]))
    return out


def _barrel(ctx: OpeningContext):
    for arc in ctx.arcs(min_span_deg=180.0):
        if not (BARREL_RADIUS[0] <= arc.radius <= BARREL_RADIUS[1]):
            continue
        if arc.radius > BARREL_MAX_RATIO * ctx.width:
            continue
        if min(dist(arc.centre, j) for j in ctx.jambs) > BARREL_NEAR_JAMB * ctx.width:
            continue
        return arc
    return None


def detect(ctx: OpeningContext) -> Match | None:
    if ctx.width <= 0:
        return None
    lo, hi = -ctx.width / 2.0, ctx.width / 2.0
    depth = max(2.0 * ctx.wall_thickness, 120.0)

    teeth = [s for s in _teeth(ctx) if abs(s.midpoint().y) <= depth]
    corrugated = (
        len(teeth) >= MIN_TEETH and coverage_of(teeth, lo, hi) >= MIN_CORRUGATION_SPAN
    )

    curtain = [
        s for s in ctx.straight_strokes(min_length=MIN_CURTAIN_COVERAGE * ctx.width)
        if along_wall(s, tol_deg=10.0)
        and abs(s.midpoint().y) <= depth
        and coverage_of([s], lo, hi) >= MIN_CURTAIN_COVERAGE
    ]
    barrel = _barrel(ctx)

    if not corrugated and not (curtain and barrel is not None):
        return None

    conf = BASE_CONFIDENCE
    if corrugated:
        conf += 0.03
    if barrel is not None:
        conf += 0.03
    return Match(
        kind="door",
        confidence=min(0.97, conf),
        meta={
            "operation": "roller",
            "clear_width_mm": round(ctx.width, 1),
            "corrugated": corrugated,
            "slats": len(teeth) if corrugated else 0,
            "barrel_radius_mm": round(barrel.radius, 1) if barrel else None,
        },
    )


SYMBOL = Symbol(
    id="door_roller",
    name="Roller shutter",
    kind="door",
    detect=detect,
    scope="opening",
    priority=45,
    description="A slatted curtain across the opening, corrugated or wound onto a barrel.",
)


def _corrugation(width: float, teeth: int, amp: float = 45.0) -> list[tuple[float, float]]:
    step = width / teeth
    return [
        (-width / 2.0 + step * i, amp if i % 2 else -amp)
        for i in range(teeth + 1)
    ]


def _circle(centre: tuple[float, float], r: float, steps: int = 20):
    return [
        (centre[0] + r * math.cos(2 * math.pi * i / steps),
         centre[1] + r * math.sin(2 * math.pi * i / steps))
        for i in range(steps + 1)
    ]


FIXTURES = [
    Fixture(
        name="corrugated shutter across a 3000 mm loading bay",
        width=3000,
        wall_thickness=200,
        strokes=[_corrugation(3000, 20)],
        expect=True,
    ),
    Fixture(
        name="corrugated shutter, finer slats",
        width=2400,
        wall_thickness=200,
        strokes=[_corrugation(2400, 32, amp=30)],
        expect=True,
    ),
    Fixture(
        name="plain curtain line wound onto a barrel at the jamb",
        width=2400,
        wall_thickness=200,
        strokes=[
            [(-1200, 60), (1200, 60)],
            _circle((-1150, 60), 220),
        ],
        expect=True,
    ),
    Fixture(
        name="a bare curtain line is a sliding leaf, not a shutter",
        width=2400,
        wall_thickness=200,
        strokes=[[(-1200, 60), (1200, 60)]],
        expect=False,
    ),
    Fixture(
        name="folding door: few long leaves, not many small slats",
        width=1800,
        wall_thickness=110,
        strokes=[[(-900, 0), (-450, 320), (0, 0), (450, 320), (900, 0)]],
        expect=False,
    ),
    Fixture(
        name="single swing door",
        width=900,
        wall_thickness=110,
        strokes=[[(-450, 0), (-450, 900)]],
        expect=False,
    ),
    Fixture(
        name="flat glazing spanning the opening",
        width=1500,
        wall_thickness=220,
        strokes=[
            [(-750, 110), (750, 110)],
            [(-750, -110), (750, -110)],
        ],
        expect=False,
    ),
    Fixture(
        name="corrugation covering only a third of the opening",
        width=3000,
        wall_thickness=200,
        strokes=[_corrugation(1000, 10)],
        expect=False,
    ),
    Fixture(name="empty opening", width=2400, strokes=[], expect=False),
]
