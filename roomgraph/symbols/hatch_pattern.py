"""Hatch patterns: dense rulings, named from the drawing's own legend.

A hatch reaches a PDF as what it was expanded into -- hundreds of short
parallel lines clipped to a boundary. Finding them is a clustering problem:
group the rulings into regions, and describe each region by the families of
parallel lines in it, their angles and their spacings.

Naming them is the interesting part, and the decision here is to *not* carry a
table of ANSI patterns. What 45-degree rulings mean is a matter of office and
national convention -- brickwork here, general material there, and Vietnamese
practice differs again. Guessing would be inventing a standard nobody agreed
to.

Instead the drawing is asked. A legend swatch is a labelled specimen of a
pattern, so the same signature is computed inside each swatch and regions are
matched against it. A plan with a legend gets its materials named in the
drawing's own vocabulary; a plan without one gets the geometry, unnamed and
honest about it.
"""

from __future__ import annotations

import math
import statistics

from ..geom import Pt, Seg, angle_of, bbox, is_parallel
from . import Fixture, Match, PlanContext, Symbol
from .hatch_legend import legend_swatches

RULING_LENGTH = (30.0, 4000.0)
SPACING_RANGE = (15.0, 400.0)      # finer than a raised floor's 600 tile grid
MIN_RULINGS = 12
MIN_FAMILY = 5
ANGLE_TOL_DEG = 6.0
MAX_SPACING_SPREAD = 0.35
CLUSTER_CELL = 2.5                 # region clustering, as a multiple of spacing
MIN_LENGTH_SPREAD = 0.08           # rulings clip to a boundary, so they vary
BULK_RULINGS = 20                  # ...unless there are simply a great many
MATCH_ANGLE_DEG = 8.0
MATCH_SPACING = 0.3


def _rulings(ctx: PlanContext) -> list[Seg]:
    return [
        s for s in ctx.straight_strokes(min_length=RULING_LENGTH[0])
        if s.length() <= RULING_LENGTH[1]
    ]


def _regions(segs: list[Seg], cell: float) -> list[list[Seg]]:
    """Connected clusters of rulings, by midpoint proximity on a grid."""
    buckets: dict[tuple[int, int], list[int]] = {}
    for i, s in enumerate(segs):
        mid = s.midpoint()
        buckets.setdefault((int(mid.x // cell), int(mid.y // cell)), []).append(i)

    seen: set[int] = set()
    out: list[list[Seg]] = []
    for start in range(len(segs)):
        if start in seen:
            continue
        stack, group = [start], []
        seen.add(start)
        while stack:
            i = stack.pop()
            group.append(segs[i])
            mid = segs[i].midpoint()
            cx, cy = int(mid.x // cell), int(mid.y // cell)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for j in buckets.get((cx + dx, cy + dy), ()):
                        if j not in seen:
                            seen.add(j)
                            stack.append(j)
        if len(group) >= MIN_RULINGS:
            out.append(group)
    return out


def _families(group: list[Seg]) -> list[tuple[float, float, list[Seg]]]:
    """(angle, spacing, members) for each family of parallel rulings.

    The members are returned, not just counted, so a region can be rebuilt from
    exactly the rulings that formed it. Re-selecting by angle afterwards lets a
    few chords of a flattened door swing back in -- some of them are parallel
    to a family by chance.
    """
    buckets: list[list[Seg]] = []
    for s in group:
        for b in buckets:
            if is_parallel(b[0].vec, s.vec, tol_deg=ANGLE_TOL_DEG):
                b.append(s)
                break
        else:
            buckets.append([s])

    out: list[tuple[float, float, list[Seg]]] = []
    for family in buckets:
        if len(family) < MIN_FAMILY:
            continue
        d = family[0].dir()
        normal = d.perp()
        offsets = sorted(s.midpoint().dot(normal) for s in family)
        gaps = [b - a for a, b in zip(offsets, offsets[1:], strict=False) if b - a > 1.0]
        if len(gaps) < MIN_FAMILY - 1:
            continue
        spacing = statistics.median(gaps)
        if not (SPACING_RANGE[0] <= spacing <= SPACING_RANGE[1]):
            continue
        tight = [g for g in gaps if abs(g - spacing) <= 0.5 * spacing]
        if len(tight) < len(gaps) * 0.6:
            continue
        if statistics.pstdev(tight) / spacing > MAX_SPACING_SPREAD:
            continue

        angle = math.degrees(angle_of(d)) % 180.0
        out.append((round(angle, 1), round(spacing, 1), family))
    return sorted(out, key=lambda f: (f[0], f[1]))


def _signature(families) -> tuple[str, list[dict]]:
    described = [
        {"angle_deg": a, "spacing_mm": sp, "rulings": len(members)}
        for a, sp, members in families
    ]
    if len(families) == 1:
        return "single", described
    if len(families) == 2:
        gap = abs(families[0][0] - families[1][0])
        gap = min(gap, 180.0 - gap)
        return ("cross" if gap > 30.0 else "double"), described
    return "compound", described


def _matches(a, b) -> bool:
    if len(a) != len(b):
        return False
    for (angle_a, space_a, _), (angle_b, space_b, _) in zip(a, b, strict=True):
        delta = abs(angle_a - angle_b)
        if min(delta, 180.0 - delta) > MATCH_ANGLE_DEG:
            return False
        if abs(space_a - space_b) > MATCH_SPACING * max(space_a, space_b):
            return False
    return True


def region_rulings(ctx: PlanContext) -> list[tuple[str | None, list[Seg]]]:
    """Each region's actual rulings, with the material name where one matched.

    Exposed for the renderer. Colouring by a region's bounding box instead
    catches whatever else falls inside it -- door swings, wall faces -- and
    shows geometry the hatch never contained.
    """
    return [(region["material"], group) for region, group in _analyse(ctx)]


def _specimens(ctx: PlanContext, rulings: list[Seg]):
    specimens: list[tuple[list[tuple[float, float, int]], str]] = []
    for centre, size, caption in legend_swatches(ctx):
        half = size * 0.75
        box = (centre.x - half, centre.y - half, centre.x + half, centre.y + half)
        inside = [
            s for s in rulings
            if box[0] <= s.midpoint().x <= box[2] and box[1] <= s.midpoint().y <= box[3]
        ]
        if len(inside) < MIN_FAMILY:
            continue
        families = _families(inside)
        if families:
            specimens.append((families, caption))
    return specimens


def detect(ctx: PlanContext) -> Match | None:
    found = _analyse(ctx)
    if not found:
        return None
    regions = [region for region, _ in found]
    specimens = _specimens(ctx, _rulings(ctx))
    named = sum(1 for r in regions if r["material"])
    conf = 0.62 + 0.10 * min(2, len(regions) - 1)
    conf += 0.16 * (named / len(regions))
    return Match(
        kind="hatch",
        confidence=min(0.92, conf),
        meta={
            "regions": regions,
            "count": len(regions),
            "named": named,
            "legend_entries": [caption for _, caption in specimens] or None,
        },
    )


def _analyse(ctx: PlanContext) -> list[tuple[dict, list[Seg]]]:
    rulings = _rulings(ctx)
    if len(rulings) < MIN_RULINGS:
        return []

    specimens = _specimens(ctx, rulings)
    swatch_boxes = [
        (centre.x - size * 0.75, centre.y - size * 0.75,
         centre.x + size * 0.75, centre.y + size * 0.75)
        for centre, size, _ in legend_swatches(ctx)
    ]

    def in_a_swatch(s: Seg) -> bool:
        mid = s.midpoint()
        return any(x0 <= mid.x <= x1 and y0 <= mid.y <= y1 for x0, y0, x1, y1 in swatch_boxes)

    body = [s for s in rulings if not in_a_swatch(s)]
    if len(body) < MIN_RULINGS:
        return []

    # Cluster on the hatch's *own* spacing. Rulings within a region sit one
    # spacing apart, so a gap of several spacings is a different region --
    # whereas a fixed cell either merges neighbours or shreds a single region.
    # Using the ruling *length* is worse again: a long ruling makes a wide cell
    # and merges regions metres apart.
    global_families = _families(body)
    spacing = (
        statistics.median([sp for _, sp, _ in global_families])
        if global_families
        else 150.0
    )
    cell = max(CLUSTER_CELL * spacing, 60.0)
    regions: list[tuple[dict, list[Seg]]] = []
    for group in _regions(body, cell=cell):
        lengths = [s.length() for s in group]
        varied = statistics.pstdev(lengths) / statistics.fmean(lengths) >= MIN_LENGTH_SPREAD
        if not varied and len(group) < BULK_RULINGS:
            continue   # equal-length evenly spaced lines are a stair or a tile grid
        families = _families(group)
        if not families:
            continue

        # Rebuild the region from exactly the family members. A flattened door
        # swing clusters in happily -- its segments are short and adjacent --
        # and while it cannot form a family, leaving it in inflates both the
        # ruling count and the region's reported extent.
        group = [s for _, _, members in families for s in members]
        if len(group) < MIN_RULINGS:
            continue

        style, described = _signature(families)
        name = next((cap for spec, cap in specimens if _matches(spec, families)), None)
        x0, y0, x1, y1 = bbox([p for s in group for p in (s.a, s.b)])
        regions.append(
            (
                {
                    "material": name,
                    "style": style,
                    "families": described,
                    "rulings": len(group),
                    "extent_mm": [round(x1 - x0, 1), round(y1 - y0, 1)],
                    "at_mm": [round((x0 + x1) / 2.0, 1), round((y0 + y1) / 2.0, 1)],
                },
                group,
            )
        )
    return regions


SYMBOL = Symbol(
    id="hatch_pattern",
    name="Hatch pattern",
    kind="hatch",
    detect=detect,
    scope="plan",
    priority=5,
    description="Regions of dense rulings, named by matching the drawing's own legend.",
)


def _rule(box, angle_deg, spacing, jitter=0.0):
    """Parallel rulings genuinely clipped to a box.

    Clipping is the point: a real hatch takes its varying line lengths from the
    boundary it fills, and rulings that overrun their region merge with the
    next one when the regions are clustered.
    """
    _ = jitter
    x0, y0, x1, y1 = box
    a = math.radians(angle_deg)
    d = Pt(math.cos(a), math.sin(a))
    n = d.perp()
    corners = [Pt(x0, y0), Pt(x1, y0), Pt(x1, y1), Pt(x0, y1)]
    offs = [p.dot(n) for p in corners]

    out = []
    off = min(offs) + spacing
    while off < max(offs):
        base = Pt(n.x * off, n.y * off)
        lo, hi = -1e12, 1e12
        for origin, delta, low, high in (
            (base.x, d.x, x0, x1),
            (base.y, d.y, y0, y1),
        ):
            if abs(delta) < 1e-12:
                if not (low <= origin <= high):
                    lo, hi = 1.0, -1.0
                    break
                continue
            t_a, t_b = (low - origin) / delta, (high - origin) / delta
            lo = max(lo, min(t_a, t_b))
            hi = min(hi, max(t_a, t_b))
        if hi - lo > 1.0:
            out.append([
                (base.x + d.x * lo, base.y + d.y * lo),
                (base.x + d.x * hi, base.y + d.y * hi),
            ])
        off += spacing
    return out


_WALL = (0.0, 0.0, 4000.0, 300.0)
_SINGLE = _rule(_WALL, 45.0, 120.0, jitter=0.2)
_CROSS = _rule((0.0, 2000.0, 4000.0, 2300.0), 45.0, 120.0, jitter=0.2) + _rule(
    (0.0, 2000.0, 4000.0, 2300.0), 135.0, 120.0, jitter=0.2
)

def _swatch(x, y, size=600.0):
    return [(x, y), (x + size, y), (x + size, y + size), (x, y + size), (x, y)]


_LEGEND_STROKES = (
    [_swatch(20000.0, 3000.0)]
    + _rule((20000.0, 3000.0, 20600.0, 3600.0), 45.0, 120.0)
    + [_swatch(20000.0, 1800.0)]
    + _rule((20000.0, 1800.0, 20600.0, 2400.0), 45.0, 120.0)
    + _rule((20000.0, 1800.0, 20600.0, 2400.0), 135.0, 120.0)
)
_LEGEND_TEXTS = [
    ("LEGEND", (20000.0, 4800.0)),
    ("BRICKWORK", (21200.0, 3300.0)),
    ("BLOCKWORK", (21200.0, 2100.0)),
]

FIXTURES = [
    Fixture(
        name="regions named from the drawing's own legend",
        scope="plan",
        strokes=_SINGLE + _CROSS + _LEGEND_STROKES,
        placed_texts=_LEGEND_TEXTS,
        expect=True,
        min_confidence=0.7,
    ),
    Fixture(
        name="one hatched region, unnamed without a legend",
        scope="plan",
        strokes=_SINGLE,
        expect=True,
    ),
    Fixture(
        name="two regions, one single and one crosshatched",
        scope="plan",
        strokes=_SINGLE + _CROSS,
        expect=True,
    ),
    Fixture(
        name="a raised floor's 600 mm tile grid is not a hatch",
        scope="plan",
        strokes=(
            [[(600.0 * i, 0.0), (600.0 * i, 6000.0)] for i in range(1, 11)]
            + [[(0.0, 600.0 * j), (6000.0, 600.0 * j)] for j in range(1, 11)]
        ),
        expect=False,
    ),
    Fixture(
        name="a stair flight: equal treads, too few to be rulings",
        scope="plan",
        strokes=[[(0.0, 280.0 * i), (1200.0, 280.0 * i)] for i in range(14)],
        expect=False,
    ),
    Fixture(
        name="an empty drawing",
        scope="plan",
        strokes=[],
        expect=False,
    ),
]
