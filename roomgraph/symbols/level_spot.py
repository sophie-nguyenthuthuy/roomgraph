"""Spot levels: the only vertical information a plan carries.

Everything else here is flat -- areas, walls, room graphs, all of it two
dimensional, because a plan has no third dimension to read. The exception is
the spot level, which states one explicitly: `FFL +3.150`, `COS +0.000`.

So this is entirely text-driven, and unapologetically so. There is nothing to
measure; the drawing simply says, and reading it is the only way the model can
know a datum at all.
"""

from __future__ import annotations

import re

from . import Fixture, Match, PlanContext, Symbol, fold_text

PREFIX = r"(?:ffl|ssl|sfl|toc|cl|cos|cot|level|lvl)"
# No leading \b: there is no word boundary before a "+", so anchoring there
# silently rejects every bare signed level.
LEVEL = rf"(?:{PREFIX})?\s*([+-]\s?\d{{1,3}}(?:[.,]\d{{2,3}}))(?!\d)"
BARE = rf"\b(?:{PREFIX})\s*([+-]?\d{{1,3}}(?:[.,]\d{{2,3}}))\b"
PLAUSIBLE = (-60.0, 400.0)   # metres: basements to towers


def _values(text: str) -> list[float]:
    folded = fold_text(text)
    out: list[float] = []
    for pattern in (LEVEL, BARE):
        for raw in re.findall(pattern, folded):
            try:
                value = float(raw.replace(" ", "").replace(",", "."))
            except ValueError:
                continue
            if PLAUSIBLE[0] <= value <= PLAUSIBLE[1]:
                out.append(value)
        if out:
            break
    return out


def detect(ctx: PlanContext) -> Match | None:
    levels: list[float] = []
    prefixed = 0
    for t in ctx.texts:
        found = _values(t.text)
        if not found:
            continue
        levels.extend(found)
        if re.search(PREFIX, fold_text(t.text)):
            prefixed += 1
    if not levels:
        return None

    unique = sorted(set(levels))
    conf = 0.62 + 0.10 * min(2, len(unique) - 1) + (0.12 if prefixed else 0.0)
    return Match(
        kind="level",
        confidence=min(0.92, conf),
        meta={
            "levels_m": unique,
            "count": len(levels),
            "datum_m": unique[0],
            "range_m": round(unique[-1] - unique[0], 3),
            "prefixed": prefixed,
        },
    )


SYMBOL = Symbol(
    id="level_spot",
    name="Spot level",
    kind="level",
    detect=detect,
    scope="plan",
    priority=10,
    description="Stated floor levels, the one piece of height a plan records.",
)


FIXTURES = [
    Fixture(
        name="two finished floor levels",
        scope="plan",
        strokes=[],
        placed_texts=[("FFL +0.000", (0.0, 0.0)), ("FFL +3.150", (5000.0, 0.0))],
        expect=True,
    ),
    Fixture(
        name="a Vietnamese datum note",
        scope="plan",
        strokes=[],
        placed_texts=[("COS +0.00", (0.0, 0.0)), ("COT -1.20", (3000.0, 0.0))],
        expect=True,
    ),
    Fixture(
        name="a bare signed level with no prefix",
        scope="plan",
        strokes=[],
        placed_texts=[("+12.450", (0.0, 0.0))],
        expect=True,
    ),
    Fixture(
        name="a room area is not a level",
        scope="plan",
        strokes=[],
        placed_texts=[("34.56 m2", (0.0, 0.0))],
        expect=False,
    ),
    Fixture(
        name="a drawing scale is not a level",
        scope="plan",
        strokes=[],
        placed_texts=[("1:100", (0.0, 0.0))],
        expect=False,
    ),
    Fixture(
        name="a level nobody could build",
        scope="plan",
        strokes=[],
        placed_texts=[("FFL +920.000", (0.0, 0.0))],
        expect=False,
    ),
    Fixture(
        name="an empty drawing",
        scope="plan",
        strokes=[],
        expect=False,
    ),
]
