"""Door schedule: the drawing's own list of doors.

Worth reading for one reason -- it can be counted against what we found. A
schedule listing twelve doors on a plan where nine were detected is a concrete,
checkable statement that something was missed, and the model raises it as a
warning rather than leaving the caller to notice.

Identified by its title and its references: `D01`, `D-02`, `CUA 03`. The table
rules are not parsed. Reading the grid would add nothing the references do not
already give.
"""

from __future__ import annotations

import re

from . import Fixture, Match, PlanContext, Symbol, fold_text

TITLE = r"\b(door\s*schedule|schedule\s*of\s*doors|bang\s*(thong\s*ke\s*)?cua|door\s*list)\b"
REFERENCE = r"^(?:d|dr|cua)\s*[-_]?\s*(\d{1,3})[a-z]?$"
MIN_REFERENCES = 2


def detect(ctx: PlanContext) -> Match | None:
    title = None
    for t in ctx.texts:
        if re.search(TITLE, fold_text(t.text)):
            title = t.text.strip()
            break
    if title is None:
        return None

    references: set[str] = set()
    for t in ctx.texts:
        token = fold_text(t.text).strip()
        m = re.fullmatch(REFERENCE, token)
        if m:
            references.add(t.text.strip().upper())
    if len(references) < MIN_REFERENCES:
        return None

    conf = 0.74 + 0.08 * min(2, (len(references) - MIN_REFERENCES) / 4.0)
    return Match(
        kind="door_schedule",
        confidence=min(0.90, conf),
        meta={
            "title": title,
            "references": sorted(references),
            "listed": len(references),
        },
    )


SYMBOL = Symbol(
    id="door_schedule",
    name="Door schedule",
    kind="door_schedule",
    detect=detect,
    scope="plan",
    priority=10,
    description="A door schedule title with the references listed beneath it.",
)


FIXTURES = [
    Fixture(
        name="a schedule listing four doors",
        scope="plan",
        strokes=[],
        placed_texts=[
            ("DOOR SCHEDULE", (0.0, 0.0)),
            ("D01", (0.0, -1000.0)), ("D02", (0.0, -2000.0)),
            ("D03", (0.0, -3000.0)), ("D04", (0.0, -4000.0)),
        ],
        expect=True,
    ),
    Fixture(
        name="a Vietnamese schedule",
        scope="plan",
        strokes=[],
        placed_texts=[
            ("BẢNG THỐNG KÊ CỬA", (0.0, 0.0)),
            ("CUA 01", (0.0, -1000.0)), ("CUA 02", (0.0, -2000.0)),
        ],
        expect=True,
    ),
    Fixture(
        name="door references with no schedule title",
        scope="plan",
        strokes=[],
        placed_texts=[("D01", (0.0, 0.0)), ("D02", (0.0, -1000.0))],
        expect=False,
    ),
    Fixture(
        name="a title with only one reference",
        scope="plan",
        strokes=[],
        placed_texts=[("DOOR SCHEDULE", (0.0, 0.0)), ("D01", (0.0, -1000.0))],
        expect=False,
    ),
    Fixture(
        name="an empty drawing",
        scope="plan",
        strokes=[],
        expect=False,
    ),
]
