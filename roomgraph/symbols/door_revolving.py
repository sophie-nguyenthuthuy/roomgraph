"""Revolving door: leaves radiating from a hub inside a drum.

Three or four leaves spaced evenly around a centre that sits in the middle of
the opening, usually inside a drawn drum circle of the same radius. Nothing
else in a plan looks like a wheel, so the spokes carry the identification and
the drum only raises confidence.

The hub position is what keeps this clear of the hinged doors. A swing or
double door anchors its leaves at a *jamb*; a revolving door anchors them at
the centre of the opening, half a width away from either.
"""

from __future__ import annotations

import math

from ..geom import Pt, angle_of, dist
from . import Fixture, Match, OpeningContext, Symbol, arc_points

MIN_LEAVES = 3
MAX_LEAVES = 6
HUB_TOL = 0.18           # hub offset from the opening centre, as a fraction of width
RADIUS_TOL = 0.25        # leaf length against the expected half-width
MAX_ANGLE_ERROR = 18.0   # degrees off perfectly even spacing
SAME_LEAF_DEG = 8.0      # leaves closer than this are one leaf drawn twice
DRUM_CENTRE_TOL = 0.20
DRUM_RADIUS_TOL = 0.25


def _spokes(ctx: OpeningContext, hub: Pt, radius: float) -> list[float]:
    """Outward bearings of leaves anchored at the hub, in degrees."""
    found: list[float] = []
    for s in ctx.straight_strokes(min_length=radius * (1.0 - RADIUS_TOL)):
        da, db = dist(s.a, hub), dist(s.b, hub)
        near, far = (s.a, s.b) if da <= db else (s.b, s.a)
        if dist(near, hub) > HUB_TOL * ctx.width:
            continue
        if abs(s.length() - radius) > RADIUS_TOL * radius:
            continue
        found.append(math.degrees(angle_of(far - hub)) % 360.0)

    unique: list[float] = []
    for a in sorted(found):
        if all(min(abs(a - b), 360.0 - abs(a - b)) > SAME_LEAF_DEG for b in unique):
            unique.append(a)
    return unique


def detect(ctx: OpeningContext) -> Match | None:
    if ctx.width <= 0:
        return None
    hub = Pt(0.0, 0.0)
    radius = ctx.width / 2.0

    bearings = _spokes(ctx, hub, radius)
    if not (MIN_LEAVES <= len(bearings) <= MAX_LEAVES):
        return None

    # Evenly spaced is the whole point: leaves of a revolving door are rigid.
    gaps = [
        (bearings[(i + 1) % len(bearings)] - bearings[i]) % 360.0
        for i in range(len(bearings))
    ]
    expected = 360.0 / len(bearings)
    error = max(abs(g - expected) for g in gaps)
    if error > MAX_ANGLE_ERROR:
        return None

    drum = None
    for arc in ctx.arcs(min_span_deg=120.0):
        if dist(arc.centre, hub) > DRUM_CENTRE_TOL * ctx.width:
            continue
        if abs(arc.radius - radius) > DRUM_RADIUS_TOL * radius:
            continue
        if drum is None or arc.span > drum.span:
            drum = arc

    conf = 0.62
    conf += 0.18 if drum is not None else 0.0
    conf += 0.08 * (1.0 - error / MAX_ANGLE_ERROR)
    conf += 0.05 if len(bearings) in (3, 4) else 0.0
    return Match(
        kind="door",
        confidence=min(0.95, conf),
        meta={
            "operation": "revolving",
            "panels": len(bearings),
            "drum_diameter_mm": round(ctx.width, 1),
            "leaf_length_mm": round(radius, 1),
            "drum_drawn": drum is not None,
            "spacing_error_deg": round(error, 2),
        },
    )


SYMBOL = Symbol(
    id="door_revolving",
    name="Revolving door",
    kind="door",
    detect=detect,
    scope="opening",
    priority=35,
    description="Three or more evenly spaced leaves radiating from a hub at the opening centre.",
)


def _wheel(width: float, leaves: int, phase: float = 0.0, hub=(0.0, 0.0)):
    r = width / 2.0
    out = []
    for k in range(leaves):
        a = math.radians(phase + 360.0 * k / leaves)
        out.append([hub, (hub[0] + r * math.cos(a), hub[1] + r * math.sin(a))])
    return out


FIXTURES = [
    Fixture(
        name="four leaves inside a 2000 mm drum",
        width=2000,
        wall_thickness=300,
        strokes=[arc_points((0, 0), 1000, 0, 360), *_wheel(2000, 4, phase=45)],
        expect=True,
    ),
    Fixture(
        name="three leaves inside a 1800 mm drum",
        width=1800,
        wall_thickness=300,
        strokes=[arc_points((0, 0), 900, 0, 360), *_wheel(1800, 3, phase=30)],
        expect=True,
    ),
    Fixture(
        name="leaves drawn without the drum circle",
        width=2000,
        wall_thickness=300,
        strokes=list(_wheel(2000, 4)),
        expect=True,
        min_confidence=0.5,
    ),
    Fixture(
        name="single swing door hinges at a jamb, not the centre",
        width=900,
        wall_thickness=110,
        strokes=[
            [(-450, 0), (-450, 900)],
            arc_points((-450, 0), 900, 90, 0),
        ],
        expect=False,
    ),
    Fixture(
        name="double door leaves also hinge at the jambs",
        width=1600,
        wall_thickness=110,
        strokes=[
            arc_points((-800, 0), 800, 90, 0),
            arc_points((800, 0), 800, 90, 180),
            [(-800, 0), (-800, 800)],
            [(800, 0), (800, 800)],
        ],
        expect=False,
    ),
    Fixture(
        name="folding door zigzag touches the centre but is not radial",
        width=1800,
        wall_thickness=110,
        strokes=[[(-900, 0), (-450, 320), (0, 0), (450, 320), (900, 0)]],
        expect=False,
    ),
    Fixture(
        name="bay window facets",
        width=2400,
        wall_thickness=220,
        strokes=[[(-1200, 0), (-700, 600), (700, 600), (1200, 0)]],
        expect=False,
    ),
    Fixture(
        name="a spiral stair beside the opening, hub well off centre",
        width=1800,
        wall_thickness=110,
        strokes=list(_wheel(1800, 4, hub=(0.0, 900.0))),
        expect=False,
    ),
    Fixture(
        name="only two leaves is not a wheel",
        width=2000,
        wall_thickness=300,
        strokes=[arc_points((0, 0), 1000, 0, 360), *_wheel(2000, 2)],
        expect=False,
    ),
    Fixture(
        name="four leaves but unevenly spaced",
        width=2000,
        wall_thickness=300,
        strokes=[
            [(0, 0), (1000, 0)],
            [(0, 0), (0, 1000)],
            [(0, 0), (-259, 966)],
            [(0, 0), (0, -1000)],
        ],
        expect=False,
    ),
    Fixture(name="empty opening", width=2000, strokes=[], expect=False),
]
