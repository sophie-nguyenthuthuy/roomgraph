"""Work out how many millimetres a PDF point represents.

A CAD export carries no units, so this is the one number everything else
depends on -- get it wrong and every area is wrong by its square. Four sources,
tried best first, and the result always says which one it used so a caller can
refuse a weak answer.

1. explicit   -- the operator passed --scale 1:50 or --mm-per-unit
2. dimension  -- dimension strings measured against the geometry they annotate
3. titleblock -- a "1:50" style ratio found in the drawing text
4. door       -- assume the most common door leaf is 900 mm
"""

from __future__ import annotations

import math
import re
import statistics
from dataclasses import dataclass

from .geom import Pt, Seg, dist, is_parallel, point_seg_distance, project_param
from .pdf.content import PageGeometry, Primitive

PT_TO_MM = 25.4 / 72.0

# 1:5 to 1:500 covers architectural plans; outside that we are misreading something.
MIN_MM_PER_PT = 1.0
MAX_MM_PER_PT = 200.0

_RATIO_RE = re.compile(r"\b1\s*[:/]\s*(\d{1,4})\b")
_NUMBER_RE = re.compile(r"^[^\d]{0,2}(\d{3,6})(?:\s*mm)?[^\d]{0,2}$", re.I)


@dataclass
class ScaleResult:
    mm_per_pt: float
    source: str
    confidence: float
    support: int = 0
    detail: str = ""

    @property
    def drawing_scale(self) -> float:
        """The 1:N denominator implied by mm_per_pt."""
        return self.mm_per_pt / PT_TO_MM

    def to_dict(self) -> dict:
        return {
            "mm_per_pt": round(self.mm_per_pt, 6),
            "drawing_scale": f"1:{round(self.drawing_scale)}",
            "source": self.source,
            "confidence": round(self.confidence, 3),
            "support": self.support,
            "detail": self.detail,
        }


def _segments_of(prims: list[Primitive]) -> list[Seg]:
    segs: list[Seg] = []
    for p in prims:
        pts = p.points
        for i in range(len(pts) - 1):
            if dist(pts[i], pts[i + 1]) > 1e-6:
                segs.append(Seg(pts[i], pts[i + 1]))
        if p.closed and len(pts) > 2 and dist(pts[-1], pts[0]) > 1e-6:
            segs.append(Seg(pts[-1], pts[0]))
    return segs


def _mode_cluster(values: list[float], rel_tol: float = 0.02) -> tuple[float, int]:
    """Largest cluster of mutually-close values; returns (median, size)."""
    if not values:
        return (0.0, 0)
    best: list[float] = []
    for v in sorted(values):
        group = [w for w in values if abs(w - v) <= rel_tol * v]
        if len(group) > len(best):
            best = group
    return (statistics.median(best), len(best))


def from_dimension_text(geo: PageGeometry) -> ScaleResult | None:
    """Match dimension strings to the segment they dimension.

    A dimension string sits beside its dimension line, parallel to it. Dividing
    the printed millimetre value by the measured point length gives mm/pt
    directly; agreement across many dimensions is what makes it trustworthy.
    """
    segs = _segments_of(geo.primitives)
    if not segs:
        return None
    candidates: list[float] = []
    for t in geo.texts:
        m = _NUMBER_RE.match(t.text.strip())
        if not m:
            continue
        value_mm = float(m.group(1))
        if not (300.0 <= value_mm <= 50000.0):
            continue
        tdir = Pt(math.cos(t.angle), math.sin(t.angle))
        radius = max(4.0 * t.height, 10.0)
        # Only the *nearest* parallel segment counts. A dimension string always
        # hugs its own dimension line, and anything further away is a wall face
        # that happens to run the same way -- matching those is how you end up
        # confidently reporting 1:75 for a 1:50 drawing.
        near: list[tuple[float, float]] = []
        for s in segs:
            if s.length() < 5.0:
                continue
            if not is_parallel(s.vec, tdir, tol_deg=6.0):
                continue
            d = point_seg_distance(t.origin, s)
            if d > radius:
                continue
            tt = project_param(t.origin, s)
            if not (0.02 <= tt <= 0.98):
                continue  # text must sit alongside the run, not past its end
            ratio = value_mm / s.length()
            if MIN_MM_PER_PT <= ratio <= MAX_MM_PER_PT:
                near.append((d, ratio))
        if near:
            near.sort(key=lambda kv: kv[0])
            candidates.append(near[0][1])
    if not candidates:
        return None
    value, support = _mode_cluster(candidates)
    if support < 1 or value <= 0:
        return None
    conf = min(0.98, 0.55 + 0.15 * support)
    return ScaleResult(value, "dimension", conf, support, f"{support} dimension string(s) agreed")


def from_titleblock(geo: PageGeometry) -> ScaleResult | None:
    for t in geo.texts:
        m = _RATIO_RE.search(t.text)
        if not m:
            continue
        denom = float(m.group(1))
        if not (5.0 <= denom <= 500.0):
            continue
        return ScaleResult(
            denom * PT_TO_MM, "titleblock", 0.6, 1, f"found '{t.text.strip()[:40]}'"
        )
    return None


def from_door_width(geo: PageGeometry, assumed_mm: float = 900.0) -> ScaleResult | None:
    """Last resort: circular arcs in a plan are door swings, and their radius is
    the leaf width. The modal leaf is 900 mm in most residential work."""
    from .geom import arc_span, fit_circle

    radii: list[float] = []
    for p in geo.primitives:
        if len(p.points) < 5 or p.closed:
            continue
        fit = fit_circle(p.points)
        if not fit:
            continue
        centre, r, resid = fit
        if r < 1e-6 or resid / r > 0.02:
            continue
        if arc_span(p.points, centre) < 0.6:
            continue
        radii.append(r)
    if not radii:
        return None
    value, support = _mode_cluster(radii, rel_tol=0.05)
    if value <= 0:
        return None
    ratio = assumed_mm / value
    if not (MIN_MM_PER_PT <= ratio <= MAX_MM_PER_PT):
        return None
    return ScaleResult(
        ratio, "door", 0.35, support, f"{support} door arc(s), assumed {assumed_mm:.0f} mm leaf"
    )


def parse_scale_arg(text: str) -> float | None:
    """Accept '1:50', '50', or '17.64mm' and return mm per point."""
    text = text.strip().lower().replace(" ", "")
    if text.endswith("mm"):
        try:
            return float(text[:-2])
        except ValueError:
            return None
    m = re.fullmatch(r"1[:/](\d+(?:\.\d+)?)", text)
    if m:
        return float(m.group(1)) * PT_TO_MM
    try:
        v = float(text)
    except ValueError:
        return None
    return v * PT_TO_MM if v >= 5 else None


def determine_scale(geo: PageGeometry, explicit: str | None = None) -> ScaleResult:
    if explicit:
        mm = parse_scale_arg(explicit)
        if mm:
            return ScaleResult(mm, "explicit", 1.0, 1, f"--scale {explicit}")
    for fn in (from_dimension_text, from_titleblock, from_door_width):
        res = fn(geo)
        if res:
            return res
    return ScaleResult(
        50 * PT_TO_MM, "default", 0.1, 0, "no scale evidence found; assumed 1:50"
    )
