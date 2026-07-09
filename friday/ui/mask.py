"""Registered screen regions to mask out of vision captures (agent GUI, etc.)."""

from __future__ import annotations

import threading
from dataclasses import dataclass

from PIL import Image, ImageDraw

_lock = threading.Lock()
_regions: dict[str, "MaskRegion"] = {}


@dataclass(frozen=True)
class MaskRegion:
    x0: int
    y0: int
    x1: int
    y1: int
    color: tuple[int, int, int] = (12, 14, 18)


def register_region(
    name: str,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    *,
    color: tuple[int, int, int] = (12, 14, 18),
) -> None:
    with _lock:
        _regions[name] = MaskRegion(x0, y0, x1, y1, color)


def unregister_region(name: str) -> None:
    with _lock:
        _regions.pop(name, None)


def clear_regions() -> None:
    with _lock:
        _regions.clear()


def apply_masks(img: Image.Image) -> Image.Image:
    with _lock:
        regions = list(_regions.values())
    if not regions:
        return img

    masked = img.copy()
    draw = ImageDraw.Draw(masked)
    w, h = masked.size
    for region in regions:
        x0 = max(0, min(w, region.x0))
        y0 = max(0, min(h, region.y0))
        x1 = max(0, min(w, region.x1))
        y1 = max(0, min(h, region.y1))
        if x1 > x0 and y1 > y0:
            draw.rectangle([x0, y0, x1, y1], fill=region.color)
    return masked
