# Adding a symbol

**The contributor unit is one symbol: one file in `roomgraph/symbols/`.**

For almost every symbol you touch nothing else -- not the geometry pipeline, not
the exporters, not the test suite. Add a file, run the tests, open a PR.
`tests/test_symbols.py` discovers your symbol and runs the fixtures you shipped
with it.

The exception is a symbol that changes what counts as a *wall*. `window_corner`
is the worked example: a corner window deletes the corner, so both walls stop
short and the room never encloses — there is no opening for a detector to be
handed. That one needed `walls.bridge_corners` before the symbol file could do
anything at all. If your symbol implies geometry the wall stage cannot see,
fix that first and the detector second.

## The local frame

A detector never sees plan coordinates. Every opening is handed to you in its
own frame:

```
                        +y
                         |
    ---- wall ----+      |      +---- wall ----
                  |             |
   ...............|......0......|...............  +x
                  |             |
    ---- wall ----+             +---- wall ----

         jamb                        jamb
      x = -w/2                     x = +w/2
```

* origin: centre of the opening, on the wall centreline
* +x: along the wall
* +y: perpendicular, into one side (which side is arbitrary -- do not rely on it)
* units: millimetres, always

So a 900 mm opening always spans `x` from -450 to +450, whether the wall runs
north-south in the drawing or at 37 degrees. Write your detector once.

Room-scope symbols get a `RoomContext` in plan coordinates instead, with the
room polygon, the strokes inside it, and `ctx.loops()` for the closed outlines
among them. Each stroke belongs to exactly one room -- the one holding most of
it -- so a fitting drawn tight against a wall is not counted twice.

The two scopes resolve differently. Openings **compete**: every detector runs
and the most confident wins, because one opening is one thing. Room features
**accumulate**: each symbol reports independently, because a room can hold a
stair and a lift and a basin at once.

## The file

```python
"""One-line summary of what this symbol looks like on a drawing."""

from __future__ import annotations

from . import Fixture, Match, OpeningContext, Symbol, along_wall, coverage_of


def detect(ctx: OpeningContext) -> Match | None:
    # Return None when it is not your symbol. Be willing to say no.
    ...
    return Match(kind="door", confidence=0.8, meta={"operation": "revolving"})


SYMBOL = Symbol(
    id="door_revolving",          # unique, snake_case, matches the filename
    name="Revolving door",
    kind="door",                  # door | window | opening | stairs | ...
    detect=detect,
    scope="opening",              # or "room"
    priority=10,                  # tie-break only; confidence decides
    description="Four leaves in a circle, drawn inside a drum.",
)

FIXTURES = [
    Fixture(name="standard four-leaf drum", width=1800, strokes=[...], expect=True),
    Fixture(name="a plain swing door is not this", width=900, strokes=[...], expect=False),
]
```

`SYMBOL` and `FIXTURES` are the entire contract.

## What the context gives you

| Call | Returns |
|---|---|
| `ctx.width` | opening width, mm |
| `ctx.wall_thickness` | mm |
| `ctx.wall_length`, `ctx.t_mid` | the wall's length and where along it this opening sits |
| `ctx.flush_end()` | `-1`, `+1` or `0`: which jamb, if either, sits at the end of the wall |
| `ctx.bridged` | True when the wall stage *invented* this opening to rebuild a missing corner |
| `ctx.jambs` | the two jamb points, `(-w/2, 0)` and `(+w/2, 0)` |
| `ctx.strokes` | every nearby polyline, as `list[list[Pt]]` |
| `ctx.arcs(min_span_deg=40)` | fitted circular arcs: centre, radius, span, residual |
| `ctx.straight_strokes(min_length)` | strokes that are a single straight run, as `Seg` |
| `ctx.loops()` | *room scope*: strokes that close back on themselves |
| `facet_chain(ctx, min_facet, max_facets)` | a path of straight facets from one jamb to the other |
| `along_wall(seg)` | is this segment parallel to the wall? |
| `coverage_of(segs, lo, hi)` | fraction of a span these segments cover |

PDF has no arc operator, so CAD exports emit curves as bezier chains. `ctx.arcs()`
fits circles to them and hands you the geometry you actually wanted.

## Confidence

Confidence is how *opening* symbols compete: every detector runs and the highest
wins. (Room symbols do not compete -- they all report -- but confidence is still
how a caller decides whether to believe one.) Rough bands:

| Range | Meaning |
|---|---|
| 0.85 - 0.98 | unmistakable -- the defining features are all present |
| 0.60 - 0.85 | typical match |
| 0.30 - 0.60 | plausible, would rather be overruled |
| below 0.30 | a fallback like `opening_plain` |

Do not return 0.95 because you are pleased with your detector. Return 0.95 when
the evidence is unambiguous, and return `None` freely -- a missed symbol falls
back to `opening_plain` and still reaches the room graph as a connection. A
false positive silently corrupts the model.

## Fixtures

Ship at least one positive and one negative. The suite enforces both.

Fixture coordinates are in the local frame, in millimetres. A fixture can also
set `wall_length`, `t_mid` and `bridged` when the symbol depends on where the
opening sits in its wall; they default to a mid-nowhere, non-bridged opening so
existing fixtures are unaffected. `arc_points()` builds arc geometry the way a
CAD exporter would:

```python
from . import arc_points

Fixture(
    name="90 degree swing hinged at the left jamb",
    width=900,
    wall_thickness=110,
    strokes=[
        [(-450, 0), (-450, 900)],            # leaf
        arc_points((-450, 0), 900, 90, 0),   # swing
    ],
    expect=True,
)
```

Good negatives are the ones that nearly fool you: the neighbouring symbol in the
library, the same symbol at the wrong scale, furniture that happens to be round.
Every existing symbol's positives are also, implicitly, your negatives --
`test_positive_fixtures_are_won_by_their_own_symbol` fails if your detector
outbids an existing one on its own fixture. That test is the real gate, and it
is why a greedy detector cannot land quietly.

For a room-scope symbol, pass `polygon=` as well:

```python
Fixture(
    name="ten treads",
    polygon=[(0, 0), (3000, 0), (3000, 4000), (0, 4000)],
    strokes=[[(200, 300 + 270 * i), (1400, 300 + 270 * i)] for i in range(10)],
    expect=True,
)
```

## Checklist

```bash
python -m unittest discover -s tests    # your fixtures + the cross-talk gate
python -m roomgraph.cli symbols         # your symbol should be listed
```

- [ ] file named after the symbol id
- [ ] docstring says what the symbol looks like on paper
- [ ] at least one positive and one negative fixture
- [ ] negatives include the symbol it is most likely to be confused with
- [ ] thresholds are named constants at module level, not inline numbers
- [ ] `detect` returns `None` rather than guessing
- [ ] if a more general symbol sees the same geometry, yours out-scores it; the
      cross-talk gate will tell you
