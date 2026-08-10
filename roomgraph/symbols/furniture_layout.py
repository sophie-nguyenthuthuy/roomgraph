"""Bed and desk layouts.

A size catalogue like `sanitary`, and honest about the same limit: a plan draws
a bed and a desk as rectangles, and only the dimensions distinguish them.

Beds are the reliable half. Mattress sizes are standardised and nothing else in
a dwelling is 2000 by 1500.

Desks are not. A 1700 by 750 rectangle is equally a bath, a worktop or a
sideboard, so a desk is claimed only where one belongs -- a bedroom, an office,
a living room -- or in the company of a bed. Alone in an unnamed room it is
left alone, because there is nothing there to decide with.
"""

from __future__ import annotations

import math

from ..geom import oriented_extent, polygon_area
from . import Fixture, Match, RoomContext, Symbol

# (name, long side range, short side range) in millimetres.
CATALOGUE: list[tuple[str, tuple[float, float], tuple[float, float]]] = [
    ("bed_single", (1850.0, 2100.0), (850.0, 1100.0)),
    ("bed_double", (1900.0, 2150.0), (1300.0, 1700.0)),
    ("bed_king", (1950.0, 2250.0), (1700.0, 2100.0)),
    ("desk", (1100.0, 1900.0), (550.0, 850.0)),
]
# No table entry on purpose. A table is 900-2400 by 850-1300, which is also a
# shower tray, a double bed seen small, and half the furniture in a plan --
# claiming it would cost more than it is worth.
DESK_ROOMS = ("bedroom", "office", "living", "study")
DESK_UNSAFE_IN = ("kitchen", "bathroom")
MIN_AREA = 0.4   # m2


def _identify(long_side: float, short_side: float) -> str | None:
    for name, longs, shorts in CATALOGUE:
        if longs[0] <= long_side <= longs[1] and shorts[0] <= short_side <= shorts[1]:
            return name
    return None


def detect(ctx: RoomContext) -> Match | None:
    found: dict[str, int] = {}
    for loop in ctx.loops():
        if abs(polygon_area(loop)) / 1e6 < MIN_AREA:
            continue
        long_side, short_side = oriented_extent(loop)
        name = _identify(long_side, short_side)
        if name:
            found[name] = found.get(name, 0) + 1

    beds = sum(n for k, n in found.items() if k.startswith("bed"))
    if "desk" in found and (
        ctx.category in DESK_UNSAFE_IN
        or (not beds and ctx.category not in DESK_ROOMS)
    ):
        del found["desk"]   # nothing here says desk rather than bath or worktop
    if not found:
        return None
    conf = 0.58 + 0.10 * min(2, sum(found.values()) - 1)
    if beds:
        conf += 0.10          # mattress sizes are the least ambiguous entry here
    if beds and ctx.category == "bedroom":
        conf += 0.08
    return Match(
        kind="furniture",
        confidence=min(0.90, conf),
        meta={
            "items": dict(sorted(found.items())),
            "count": sum(found.values()),
            "beds": beds,
        },
    )


SYMBOL = Symbol(
    id="furniture_layout",
    name="Bed and desk layout",
    kind="furniture",
    detect=detect,
    scope="room",
    priority=5,
    description="Outlines matching standard bed and desk sizes.",
)


_BEDROOM = [(0, 0), (4000, 0), (4000, 3500), (0, 3500)]


def _box(x, y, w, h, angle=0.0):
    c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    pts = [(0.0, 0.0), (w, 0.0), (w, h), (0.0, h), (0.0, 0.0)]
    return [(x + px * c - py * s, y + px * s + py * c) for px, py in pts]


FIXTURES = [
    Fixture(
        name="a double bed and a desk",
        polygon=_BEDROOM,
        category="bedroom",
        strokes=[_box(200, 200, 2000, 1500), _box(2500, 200, 1400, 700)],
        expect=True,
    ),
    Fixture(
        name="a single bed",
        polygon=_BEDROOM,
        strokes=[_box(200, 200, 1900, 900)],
        expect=True,
    ),
    Fixture(
        name="a bed drawn at an angle",
        polygon=_BEDROOM,
        strokes=[_box(500, 500, 2000, 1500, angle=20)],
        expect=True,
    ),
    Fixture(
        name="a desk in a kitchen is a worktop",
        polygon=_BEDROOM,
        category="kitchen",
        strokes=[_box(200, 200, 1400, 700)],
        expect=False,
    ),
    Fixture(
        name="a desk-shaped rectangle alone in an unnamed room could be a bath",
        polygon=_BEDROOM,
        strokes=[_box(200, 200, 1700, 750)],
        expect=False,
    ),
    Fixture(
        name="the same rectangle beside a bed is a desk",
        polygon=_BEDROOM,
        strokes=[_box(200, 200, 1700, 750), _box(200, 1200, 2000, 1500)],
        expect=True,
    ),
    Fixture(
        name="a bath in a bathroom is never a desk",
        polygon=_BEDROOM,
        category="bathroom",
        strokes=[_box(200, 200, 1700, 750)],
        expect=False,
    ),
    Fixture(
        name="an empty bedroom",
        polygon=_BEDROOM,
        strokes=[],
        expect=False,
    ),
]
