"""Shared colours, so the SVG and the GIF tell the same story."""

from __future__ import annotations

RGB = tuple[int, int, int]

BACKGROUND: RGB = (250, 249, 246)
WALL: RGB = (38, 42, 50)
INK: RGB = (28, 31, 38)
MUTED: RGB = (132, 138, 150)
DOOR: RGB = (58, 132, 96)
WINDOW: RGB = (58, 116, 186)
OPENING: RGB = (176, 132, 60)
EDGE_WALL: RGB = (198, 200, 206)

CATEGORY: dict[str, RGB] = {
    "living": (232, 168, 90),
    "bedroom": (126, 168, 219),
    "kitchen": (226, 122, 110),
    "bathroom": (120, 199, 191),
    "dining": (214, 148, 196),
    "balcony": (168, 205, 130),
    "hall": (176, 180, 194),
    "stairs": (200, 178, 140),
    "storage": (158, 166, 190),
    "office": (150, 160, 220),
    "garage": (154, 154, 154),
    "worship": (208, 168, 88),
    "technical": (140, 150, 155),
    "other": (185, 190, 200),
    "unknown": (205, 207, 213),
}


def colour_for(category: str) -> RGB:
    return CATEGORY.get(category, CATEGORY["unknown"])


def hex_of(rgb: RGB) -> str:
    return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"


def kind_colour(kind: str) -> RGB:
    return {"door": DOOR, "window": WINDOW, "opening": OPENING}.get(kind, MUTED)
