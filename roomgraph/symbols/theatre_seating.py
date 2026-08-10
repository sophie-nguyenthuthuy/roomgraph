"""Theatre seating: many identical seats in regular rows.

No single seat is identifiable -- a 500 by 550 rectangle is nothing in
particular. The signature is the *repetition*: a dozen or more outlines of the
same size, in rows at a regular pitch. Nothing else in a building repeats like
an auditorium does.

Rows are found rather than assumed straight, so curved and raked seating both
work: seats are grouped by their distance along the room's dominant seat axis,
and the pitch between those groups is what has to be regular.
"""

from __future__ import annotations

import statistics

from ..geom import Pt, oriented_extent, polygon_area
from . import Fixture, Match, RoomContext, Symbol

SEAT_WIDTH = (420.0, 700.0)
SEAT_DEPTH = (400.0, 800.0)
MIN_SEATS = 12
MAX_SIZE_SPREAD = 0.12
ROW_PITCH = (600.0, 1400.0)
MAX_PITCH_SPREAD = 0.25
ROW_TOLERANCE = 250.0


def detect(ctx: RoomContext) -> Match | None:
    seats: list[tuple[Pt, float]] = []
    for loop in ctx.loops():
        area = abs(polygon_area(loop)) / 1e6
        if not (0.15 <= area <= 0.6):
            continue
        long_side, short_side = oriented_extent(loop)
        if not (SEAT_DEPTH[0] <= long_side <= SEAT_DEPTH[1]):
            continue
        if not (SEAT_WIDTH[0] <= short_side <= SEAT_WIDTH[1]):
            continue
        centre = Pt(
            sum(p.x for p in loop) / len(loop), sum(p.y for p in loop) / len(loop)
        )
        seats.append((centre, long_side))

    if len(seats) < MIN_SEATS:
        return None
    sizes = [s for _, s in seats]
    if statistics.pstdev(sizes) / statistics.fmean(sizes) > MAX_SIZE_SPREAD:
        return None   # assorted sizes are furniture, not an auditorium

    rows, pitch, spread = _rows(seats)
    if rows < 2:
        return None

    conf = 0.68
    conf += 0.10 * min(1.0, (len(seats) - MIN_SEATS) / 40.0)
    conf += 0.08 * (1.0 - min(1.0, spread / MAX_PITCH_SPREAD))
    conf += 0.08 if ctx.category == "auditorium" else 0.0
    return Match(
        kind="seating",
        confidence=min(0.93, conf),
        meta={
            "seats": len(seats),
            "rows": rows,
            "row_pitch_mm": round(pitch, 1),
            "seat_mm": round(statistics.median(sizes), 1),
        },
    )


def _rows(seats: list[tuple[Pt, float]]) -> tuple[int, float, float]:
    """Group seats into rows along whichever axis gives the most regular pitch."""
    best = (0, 0.0, 1.0)
    for axis in (Pt(0.0, 1.0), Pt(1.0, 0.0)):
        positions = sorted(c.dot(axis) for c, _ in seats)
        groups: list[list[float]] = [[positions[0]]]
        for value in positions[1:]:
            if value - groups[-1][-1] <= ROW_TOLERANCE:
                groups[-1].append(value)
            else:
                groups.append([value])
        if len(groups) < 2:
            continue
        centres = [statistics.fmean(g) for g in groups]
        gaps = [b - a for a, b in zip(centres, centres[1:], strict=False)]
        mean = statistics.fmean(gaps)
        if not (ROW_PITCH[0] <= mean <= ROW_PITCH[1]):
            continue
        spread = statistics.pstdev(gaps) / mean if mean else 1.0
        if spread > MAX_PITCH_SPREAD:
            continue
        if len(groups) > best[0]:
            best = (len(groups), mean, spread)
    return best


SYMBOL = Symbol(
    id="theatre_seating",
    name="Theatre seating",
    kind="seating",
    detect=detect,
    scope="room",
    priority=20,
    description="A dozen or more identical seats in rows at a regular pitch.",
)


_HALL = [(0, 0), (12000, 0), (12000, 12000), (0, 12000)]


def _seat(x, y, w=520, d=550):
    return [(x, y), (x + w, y), (x + w, y + d), (x, y + d), (x, y)]


def _rows_of(cols, rows, pitch=900, gap=580, x0=1000, y0=1000, curve=0.0):
    out = []
    for r in range(rows):
        for c in range(cols):
            bow = curve * ((c - (cols - 1) / 2) ** 2) / max(1, (cols - 1) ** 2 / 4)
            out.append(_seat(x0 + gap * c, y0 + pitch * r + bow))
    return out


FIXTURES = [
    Fixture(
        name="six rows of eight seats",
        polygon=_HALL,
        category="auditorium",
        strokes=_rows_of(8, 6),
        expect=True,
    ),
    Fixture(
        name="curved rows, unnamed room",
        polygon=_HALL,
        strokes=_rows_of(9, 4, curve=180.0),
        expect=True,
    ),
    Fixture(
        name="a single row is not an auditorium",
        polygon=_HALL,
        strokes=_rows_of(10, 1),
        expect=False,
    ),
    Fixture(
        name="eight chairs round a table is not seating rows",
        polygon=_HALL,
        strokes=_rows_of(4, 2),
        expect=False,
    ),
    Fixture(
        name="rows at a pitch far too wide to be seating",
        polygon=_HALL,
        strokes=_rows_of(8, 6, pitch=2400),
        expect=False,
    ),
    Fixture(
        name="an empty hall",
        polygon=_HALL,
        strokes=[],
        expect=False,
    ),
]
