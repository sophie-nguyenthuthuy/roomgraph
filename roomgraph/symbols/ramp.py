"""Ramp: a graded band, identified by its gradient label.

Geometry alone cannot do this one. A ramp in plan is a band between two lines
with an arrow -- which is also a corridor, a travelator, or nothing at all. The
gradient is what makes it a ramp, and the gradient is written on the drawing:
`1:12`, `1:20`, `RAMP`, `DỐC`.

So this symbol reads the room's own labels alongside its geometry, and returns
None when the drawing does not say. Guessing "ramp" from a rectangle would put
a slope into a model that has no other way to know about one.
"""

from __future__ import annotations

import re

from ..geom import is_parallel
from . import Fixture, Match, RoomContext, Symbol

GRADIENT = r"\b1\s*[:/]\s*(\d{1,2})\b"
WORDS = r"\b(ramp|dôc|doc|d[ốô]c|slope|incline)\b"
GRADIENT_RANGE = (8, 25)     # 1:8 is steep, 1:25 is barely a slope
MIN_LENGTH = 2500.0
BAND_WIDTH = (900.0, 3500.0)
MAX_CROSSERS = 3             # more than a few crossing lines means steps, not a slope
MAX_LENGTH_MISMATCH = 0.3    # the two sides of a ramp run together
MIN_OVERLAP = 0.7


def _gradient(ctx: RoomContext) -> int | None:
    for t in ctx.texts:
        m = re.search(GRADIENT, t)
        if m and GRADIENT_RANGE[0] <= int(m.group(1)) <= GRADIENT_RANGE[1]:
            return int(m.group(1))
    return None


def detect(ctx: RoomContext) -> Match | None:
    gradient = _gradient(ctx)
    named = ctx.text_matches(WORDS)
    if gradient is None and not named:
        return None

    sides = ctx.straight_strokes(min_length=MIN_LENGTH)
    chosen = None
    for i, a in enumerate(sides):
        for b in sides[i + 1:]:
            if not is_parallel(a.vec, b.vec, tol_deg=6.0):
                continue
            # The two sides of a ramp are a matched pair: similar length, and
            # running alongside each other. A wall paired with some unrelated
            # line metres away satisfies neither.
            if abs(a.length() - b.length()) > MAX_LENGTH_MISMATCH * max(
                a.length(), b.length()
            ):
                continue
            d = a.dir()
            n = d.perp()
            offset = (b.a - a.a).dot(n)   # signed: the interior test needs the side
            gap = abs(offset)
            if not (BAND_WIDTH[0] <= gap <= BAND_WIDTH[1]):
                continue
            ta = sorted((a.a.dot(d), a.b.dot(d)))
            tb = sorted((b.a.dot(d), b.b.dot(d)))
            overlap = min(ta[1], tb[1]) - max(ta[0], tb[0])
            if overlap < MIN_OVERLAP * min(a.length(), b.length()):
                continue

            # A crosser only counts if it lies *inside* the band. Otherwise a
            # wall face at the far side of the room, or a neighbouring
            # escalator's treads, would each look like a step.
            crossers = 0
            for s in ctx.straight_strokes(min_length=0.6 * gap):
                if not is_parallel(s.vec, n, tol_deg=12.0):
                    continue
                mid = s.midpoint()
                along = mid.dot(d)
                across = (mid - a.a).dot(n)
                if not (max(ta[0], tb[0]) <= along <= min(ta[1], tb[1])):
                    continue
                if min(0.0, offset) - 1.0 <= across <= max(0.0, offset) + 1.0:
                    crossers += 1
            if crossers > MAX_CROSSERS:
                continue  # a stepped band is a stair, not a ramp
            chosen = (a, gap)
            break
        if chosen:
            break
    if chosen is None:
        return None

    a, gap = chosen

    conf = 0.70 if gradient is not None else 0.62
    conf += 0.10 if (gradient is not None and named) else 0.0
    conf += 0.08 * min(1.0, a.length() / 8000.0)
    return Match(
        kind="ramp",
        confidence=min(0.92, conf),
        meta={
            "gradient": f"1:{gradient}" if gradient else None,
            "length_mm": round(a.length(), 1),
            "width_mm": round(gap, 1),
            "label": (named or "").strip() or None,
        },
    )


SYMBOL = Symbol(
    id="ramp",
    name="Ramp",
    kind="ramp",
    detect=detect,
    scope="room",
    priority=15,
    description="A band between two long parallel lines, carrying a gradient label.",
)


_ROOM = [(0, 0), (3000, 0), (3000, 9000), (0, 9000)]
_BAND = [[(600, 500), (600, 8500)], [(2400, 500), (2400, 8500)]]

FIXTURES = [
    Fixture(
        name="an 8 m band labelled 1:12",
        polygon=_ROOM,
        texts=["RAMP 1:12"],
        strokes=_BAND,
        expect=True,
    ),
    Fixture(
        name="a band labelled only with the Vietnamese word",
        polygon=_ROOM,
        texts=["DỐC LÊN"],
        strokes=_BAND,
        expect=True,
    ),
    Fixture(
        name="an unlabelled band is a corridor, not a ramp",
        polygon=_ROOM,
        strokes=_BAND,
        expect=False,
    ),
    Fixture(
        name="a gradient label with no band drawn",
        polygon=_ROOM,
        texts=["RAMP 1:12"],
        strokes=[],
        expect=False,
    ),
    Fixture(
        name="1:200 is a drawing scale, not a ramp gradient",
        polygon=_ROOM,
        texts=["1:200"],
        strokes=_BAND,
        expect=False,
    ),
    Fixture(
        name="a labelled band full of steps is a stair",
        polygon=_ROOM,
        texts=["RAMP 1:12"],
        strokes=[*_BAND, *[[(600, 800 + 300 * i), (2400, 800 + 300 * i)] for i in range(8)]],
        expect=False,
    ),
]
