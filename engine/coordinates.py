"""Normalize model step output and map coordinates to the physical screen."""

from __future__ import annotations

import re
from typing import Any


def fit_image_size(
    source_size: tuple[int, int],
    max_size: tuple[int, int],
) -> tuple[int, int]:
    """Scale down to fit inside max_size while preserving aspect ratio."""
    src_w, src_h = source_size
    max_w, max_h = max_size
    if src_w <= 0 or src_h <= 0:
        return max_size
    scale = min(max_w / src_w, max_h / src_h, 1.0)
    return max(1, int(src_w * scale)), max(1, int(src_h * scale))


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _extract_pair(data: dict, *keys: str) -> tuple[int | None, int | None]:
    for key in keys:
        if key not in data:
            continue
        raw = data[key]
        if isinstance(raw, dict):
            x = _as_int(raw.get("x"))
            y = _as_int(raw.get("y"))
            if x is not None and y is not None:
                return x, y
        if isinstance(raw, (list, tuple)) and len(raw) >= 2:
            x = _as_int(raw[0])
            y = _as_int(raw[1])
            if x is not None and y is not None:
                return x, y
    return None, None


def _normalize_point(
    x: int | None,
    y: int | None,
    image_size: tuple[int, int],
) -> tuple[int | None, int | None]:
    if x is None or y is None:
        return None, None

    img_w, img_h = image_size
    # Models sometimes emit 0–1 normalized coordinates.
    if 0 <= x <= 1 and 0 <= y <= 1:
        x = int(round(x * img_w))
        y = int(round(y * img_h))

    return x, y


def _scale_point(
    x: int | None,
    y: int | None,
    image_size: tuple[int, int],
    native_size: tuple[int, int],
) -> tuple[int | None, int | None]:
    if x is None or y is None:
        return None, None

    img_w, img_h = image_size
    native_w, native_h = native_size
    if img_w <= 0 or img_h <= 0:
        return x, y

    return (
        int(round(x * native_w / img_w)),
        int(round(y * native_h / img_h)),
    )


def _extract_win_search_text(step: dict) -> str:
    """Recover WIN_SEARCH query from alternate or missing field names."""
    for key in ("text", "query", "search", "app"):
        val = step.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()

    desc = str(step.get("description", ""))
    if not desc:
        return ""

    quoted = re.search(r"""['"]([^'"]{1,80})['"]""", desc)
    if quoted:
        return quoted.group(1).strip()

    unquoted = re.search(
        r"(?:search(?:ing)?(?:\s+for)?|open(?:ing)?|launch(?:ing)?)\s+"
        r"([A-Za-z][\w\s.-]{0,40})",
        desc,
        re.I,
    )
    if unquoted:
        return unquoted.group(1).strip().rstrip(".")

    desc_lower = desc.lower()
    for app in (
        "notepad", "chrome", "edge", "explorer", "calculator", "paint",
        "word", "excel", "powershell", "cmd",
    ):
        if app in desc_lower:
            return app

    return ""


def normalize_step(step: dict, image_size: tuple[int, int]) -> dict:
    """Coerce alternate VLM field names and coordinate formats."""
    normalized = dict(step)
    action = str(normalized.get("action", "")).upper()
    normalized["action"] = action

    if action == "WIN_SEARCH" and not str(normalized.get("text") or "").strip():
        normalized["text"] = _extract_win_search_text(normalized)

    x, y = _extract_pair(
        normalized,
        "coordinates",
        "coordinate",
        "position",
        "point",
        "click",
        "location",
    )
    if x is None:
        x = _as_int(normalized.get("x"))
    if y is None:
        y = _as_int(normalized.get("y"))
    x, y = _normalize_point(x, y, image_size)
    if x is not None and y is not None:
        normalized["x"] = x
        normalized["y"] = y

    x2, y2 = _extract_pair(normalized, "end", "end_position", "target")
    if x2 is None:
        x2 = _as_int(normalized.get("x2"))
    if y2 is None:
        y2 = _as_int(normalized.get("y2"))
    x2, y2 = _normalize_point(x2, y2, image_size)
    if x2 is not None and y2 is not None:
        normalized["x2"] = x2
        normalized["y2"] = y2

    return normalized


def scale_step_to_screen(
    step: dict,
    image_size: tuple[int, int],
    native_size: tuple[int, int],
) -> dict:
    """Map coordinates from screenshot space to physical monitor pixels."""
    if image_size == native_size:
        return step

    scaled = dict(step)
    x, y = _scale_point(
        _as_int(scaled.get("x")),
        _as_int(scaled.get("y")),
        image_size,
        native_size,
    )
    if x is not None and y is not None:
        scaled["x"] = x
        scaled["y"] = y

    x2, y2 = _scale_point(
        _as_int(scaled.get("x2")),
        _as_int(scaled.get("y2")),
        image_size,
        native_size,
    )
    if x2 is not None and y2 is not None:
        scaled["x2"] = x2
        scaled["y2"] = y2

    return scaled


def prepare_steps_for_execution(
    steps: list[dict],
    image_size: tuple[int, int],
    native_size: tuple[int, int],
) -> list[dict]:
    prepared: list[dict] = []
    for step in steps:
        normalized = normalize_step(step, image_size)
        prepared.append(scale_step_to_screen(normalized, image_size, native_size))
    return prepared
