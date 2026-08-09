"""Faces to rooms: areas, names, and a sanity check against the drawing's own labels.

Two areas are reported and they are not interchangeable. `area_gross_m2` is
measured to wall centrelines -- the convention behind most published apartment
figures. `area_net_m2` is the usable floor inside the finishes, obtained by
offsetting each edge inward by half the thickness of the wall it came from.

Where the drawing prints its own area, we compare and report the delta. A
mismatch is the loudest available signal that the scale was misread.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from .geom import (
    Pt,
    offset_polygon,
    point_in_polygon,
    polygon_area,
    polygon_centroid,
    polygon_perimeter,
    representative_point,
)
from .pdf.content import TextRun
from .planar import Arrangement, Face
from .walls import Wall

MIN_ROOM_AREA_M2 = 0.7
MAX_SLIVER_ASPECT = 0.012  # area / perimeter^2 below this is a wall sliver, not a room

_AREA_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(?:m2|m²|sqm|m\^2)\b", re.I
)

# Vietnamese first: this is the vocabulary the plans in front of us use.
CATEGORY_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("bathroom", ("wc", "ve sinh", "vesinh", "toilet", "bath", "tam", "nha tam", "restroom")),
    ("kitchen", ("bep", "kitchen", "nha bep", "cook")),
    ("bedroom", ("phong ngu", "ngu", "bedroom", "bed", "master", "pn")),
    ("living", ("phong khach", "khach", "living", "lounge", "sinh hoat", "phong sinh hoat", "studio")),
    ("dining", ("an", "phong an", "dining", "ban an")),
    ("balcony", ("ban cong", "bancong", "balcony", "loggia", "logia", "san phoi")),
    ("hall", ("hall", "sanh", "hanh lang", "corridor", "loi vao", "entry", "foyer", "tien sanh")),
    ("stairs", ("cau thang", "thang", "stair", "staircase")),
    ("storage", ("kho", "storage", "closet", "tu do", "utility", "giat", "laundry")),
    ("office", ("lam viec", "office", "study", "phong lam viec", "doc sach")),
    ("garage", ("garage", "gara", "de xe", "parking", "xe")),
    ("worship", ("tho", "ban tho", "phong tho", "altar")),
    ("technical", ("ky thuat", "shaft", "hop gen", "duct", "plant")),
]


def _fold(s: str) -> str:
    """Strip Vietnamese diacritics so 'PHÒNG NGỦ' and 'PHONG NGU' match."""
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.replace("đ", "d").replace("Đ", "D")
    return re.sub(r"[^a-z0-9 ]+", " ", s.lower()).strip()


def classify(name: str | None) -> str:
    if not name:
        return "unknown"
    folded = _fold(name)
    tokens = set(folded.split())
    for category, keys in CATEGORY_KEYWORDS:
        for k in keys:
            if " " in k:
                if k in folded:
                    return category
            elif k in tokens:
                return category
    return "other"


@dataclass
class Room:
    id: str
    face: int
    polygon: list[Pt]
    area_gross_m2: float
    area_net_m2: float
    perimeter_m: float
    centroid: Pt
    label_point: Pt
    name: str | None = None
    category: str = "unknown"
    labelled_area_m2: float | None = None
    area_delta_pct: float | None = None
    texts: list[str] = field(default_factory=list)

    def area_check(self) -> str:
        if self.area_delta_pct is None:
            return "unchecked"
        return "ok" if abs(self.area_delta_pct) <= 3.0 else "mismatch"


def _edge_thicknesses(arr: Arrangement, face: Face, walls: list[Wall]) -> list[float]:
    out: list[float] = []
    for di in face.darts:
        w = arr.darts[di].wall
        t = walls[w].thickness if (w is not None and 0 <= w < len(walls)) else 100.0
        out.append(t / 2.0)
    return out


def _is_sliver(ring: list[Pt]) -> bool:
    per = polygon_perimeter(ring)
    if per <= 0:
        return True
    return abs(polygon_area(ring)) / (per * per) < MAX_SLIVER_ASPECT


def build_rooms(
    arr: Arrangement,
    walls: list[Wall],
    texts: list[TextRun],
    mm_per_pt: float,
    min_area_m2: float = MIN_ROOM_AREA_M2,
) -> list[Room]:
    rooms: list[Room] = []
    for face in arr.inner_faces():
        area_m2 = face.area / 1e6
        if area_m2 < min_area_m2 or _is_sliver(face.ring):
            continue

        half = _edge_thicknesses(arr, face, walls)
        net_ring = offset_polygon(face.ring, half)
        net_m2 = abs(polygon_area(net_ring)) / 1e6
        if not (0.2 * area_m2 <= net_m2 <= area_m2):
            net_m2 = area_m2  # offset collapsed or inverted; fall back honestly

        rooms.append(
            Room(
                id=f"R{len(rooms) + 1:03d}",
                face=face.index,
                polygon=list(face.ring),
                area_gross_m2=round(area_m2, 3),
                area_net_m2=round(net_m2, 3),
                perimeter_m=round(polygon_perimeter(face.ring) / 1000.0, 3),
                centroid=polygon_centroid(face.ring),
                label_point=representative_point(face.ring),
            )
        )

    _attach_labels(rooms, texts, mm_per_pt)
    return rooms


def _attach_labels(rooms: list[Room], texts: list[TextRun], mm_per_pt: float) -> None:
    """Assign each text run to the room containing it.

    The tallest text in a room is its name; a `12.5 m2` string is its printed
    area. Text outside every room (title block, dimensions) is simply dropped.
    """
    inside: dict[int, list[TextRun]] = {}
    for t in texts:
        p = Pt(t.origin.x * mm_per_pt, t.origin.y * mm_per_pt)
        for i, r in enumerate(rooms):
            if point_in_polygon(p, r.polygon):
                inside.setdefault(i, []).append(t)
                break

    for i, room in enumerate(rooms):
        runs = sorted(inside.get(i, []), key=lambda t: -t.height)
        room.texts = [t.text for t in runs]
        for t in runs:
            m = _AREA_RE.search(t.text)
            if m and room.labelled_area_m2 is None:
                try:
                    room.labelled_area_m2 = float(m.group(1).replace(",", "."))
                except ValueError:
                    pass
        for t in runs:
            if _AREA_RE.search(t.text):
                continue
            cleaned = t.text.strip()
            if len(cleaned) >= 2 and not cleaned.replace(".", "").isdigit():
                room.name = cleaned
                break
        room.category = classify(room.name)
        if room.labelled_area_m2 and room.labelled_area_m2 > 0:
            room.area_delta_pct = round(
                100.0 * (room.area_gross_m2 - room.labelled_area_m2) / room.labelled_area_m2, 2
            )
