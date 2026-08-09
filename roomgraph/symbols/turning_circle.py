"""Wheelchair turning circle: a 1500 mm circle of clear floor.

An accessibility mark rather than a thing that exists, which makes the *clear*
part load-bearing. A circle of the right diameter with a stair newel or a
fitting inside it is not a turning circle -- it is some other circle. So the
interior must be empty, which is exactly what the mark asserts.

That test also keeps it away from spiral stairs, whose enclosing circle is the
same size and full of treads.
"""

from __future__ import annotations

import math

from ..geom import arc_span, dist, fit_circle
from . import Fixture, Match, RoomContext, Symbol

DIAMETER_RANGE = (1400.0, 1900.0)   # 1500 is the common standard, 1800 generous
MIN_SPAN_DEG = 330.0
MAX_RESIDUAL = 0.05
CLEAR_RATIO = 0.6                   # interior that must contain nothing else


def detect(ctx: RoomContext) -> Match | None:
    circles = []
    for pts in ctx.strokes:
        if len(pts) < 6:
            continue
        fit = fit_circle(pts)
        if not fit:
            continue
        centre, radius, resid = fit
        if radius <= 0 or resid / radius > MAX_RESIDUAL:
            continue
        if not (DIAMETER_RANGE[0] <= 2 * radius <= DIAMETER_RANGE[1]):
            continue
        if math.degrees(arc_span(pts, centre)) < MIN_SPAN_DEG:
            continue
        circles.append((centre, radius, pts))
    if not circles:
        return None

    for centre, radius, own in circles:
        clear = True
        for pts in ctx.strokes:
            if pts is own:
                continue
            if any(dist(q, centre) <= CLEAR_RATIO * radius for q in pts):
                clear = False
                break
        if not clear:
            continue
        return Match(
            kind="turning_circle",
            confidence=0.86 if abs(2 * radius - 1500.0) <= 120.0 else 0.78,
            meta={
                "diameter_mm": round(2 * radius, 1),
                "centre_mm": [round(centre.x, 1), round(centre.y, 1)],
            },
        )
    return None


SYMBOL = Symbol(
    id="turning_circle",
    name="Wheelchair turning circle",
    kind="turning_circle",
    detect=detect,
    scope="room",
    priority=25,
    description="An empty circle of about 1500 mm marking clear manoeuvring space.",
)


_WC = [(0, 0), (2400, 0), (2400, 2400), (0, 2400)]


def _circle(centre, r, steps=32):
    return [
        (centre[0] + r * math.cos(2 * math.pi * i / steps),
         centre[1] + r * math.sin(2 * math.pi * i / steps))
        for i in range(steps + 1)
    ]


def _spokes(centre, r, n):
    return [
        [centre, (centre[0] + r * math.cos(2 * math.pi * i / n),
                  centre[1] + r * math.sin(2 * math.pi * i / n))]
        for i in range(n)
    ]


FIXTURES = [
    Fixture(
        name="a clear 1500 mm circle",
        polygon=_WC,
        strokes=[_circle((1200, 1200), 750)],
        expect=True,
    ),
    Fixture(
        name="a generous 1800 mm circle",
        polygon=_WC,
        strokes=[_circle((1200, 1200), 900)],
        expect=True,
    ),
    Fixture(
        name="a spiral stair fills its circle with treads",
        polygon=_WC,
        strokes=[_circle((1200, 1200), 900), *_spokes((1200, 1200), 900, 12)],
        expect=False,
    ),
    Fixture(
        name="a 900 mm circle is too small to turn in",
        polygon=_WC,
        strokes=[_circle((1200, 1200), 450)],
        expect=False,
    ),
    Fixture(
        name="a square of the right size is not a circle",
        polygon=_WC,
        strokes=[[(450, 450), (1950, 450), (1950, 1950), (450, 1950), (450, 450)]],
        expect=False,
    ),
    Fixture(
        name="an empty room",
        polygon=_WC,
        strokes=[],
        expect=False,
    ),
]
