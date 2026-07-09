"""Normalize model coordinates and map image space → physical screen."""

from __future__ import annotations

import re
from typing import Any

from friday.config import resolve_coord_space
from friday.types import ActionStep

GRID_MAX = 1000


def uses_grid_coords() -> bool:
    return resolve_coord_space() == "grid1000"


def clamp_to_image(x: int, y: int, image_size: tuple[int, int]) -> tuple[int, int]:
    iw, ih = image_size
    return max(0, min(x, iw - 1)), max(0, min(y, ih - 1))


def model_point_to_image(
    x: int, y: int, image_size: tuple[int, int],
) -> tuple[int, int]:
    """Convert a point from the model's output space to image pixels."""
    if uses_grid_coords():
        iw, ih = image_size
        x = int(round(x / GRID_MAX * iw))
        y = int(round(y / GRID_MAX * ih))
    return clamp_to_image(x, y, image_size)


def image_point_to_model(
    x: int, y: int, image_size: tuple[int, int],
) -> tuple[int, int]:
    """Convert image pixels to the model's coordinate space (for prompts)."""
    if uses_grid_coords():
        iw, ih = image_size
        if iw > 0 and ih > 0:
            return int(round(x / iw * GRID_MAX)), int(round(y / ih * GRID_MAX))
    return x, y


def fit_image_size(
    source_size: tuple[int, int],
    max_size: tuple[int, int],
) -> tuple[int, int]:
    src_w, src_h = source_size
    max_w, max_h = max_size
    if src_w <= 0 or src_h <= 0:
        return max_size
    scale = min(max_w / src_w, max_h / src_h, 1.0)
    return max(1, int(src_w * scale)), max(1, int(src_h * scale))


def as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def image_to_native(
    x: int, y: int,
    image_size: tuple[int, int],
    native_size: tuple[int, int],
) -> tuple[int, int]:
    iw, ih = image_size
    nw, nh = native_size
    if (iw, ih) == (nw, nh) or iw <= 0 or ih <= 0:
        return x, y
    return int(round(x * nw / iw)), int(round(y * nh / ih))


def native_to_image(
    x: int, y: int,
    native_size: tuple[int, int],
    image_size: tuple[int, int],
) -> tuple[int, int]:
    nw, nh = native_size
    iw, ih = image_size
    if (nw, nh) == (iw, ih) or nw <= 0 or nh <= 0:
        return x, y
    return int(round(x * iw / nw)), int(round(y * ih / nh))


def _extract_pair(data: dict, *keys: str) -> tuple[int | None, int | None]:
    for key in keys:
        if key not in data:
            continue
        raw = data[key]
        if isinstance(raw, dict):
            x, y = as_int(raw.get("x")), as_int(raw.get("y"))
            if x is not None and y is not None:
                return x, y
        if isinstance(raw, (list, tuple)) and len(raw) >= 2:
            x, y = as_int(raw[0]), as_int(raw[1])
            if x is not None and y is not None:
                return x, y
    return None, None


def _is_unit_float(value: Any) -> bool:
    """True for fractional 0–1 floats (or dotted strings), not integer pixels."""
    if isinstance(value, bool) or value is None:
        return False
    if isinstance(value, int):
        return False
    if isinstance(value, float):
        return 0.0 <= value <= 1.0
    if isinstance(value, str) and "." in value:
        try:
            f = float(value)
            return 0.0 <= f <= 1.0
        except ValueError:
            return False
    return False


def _normalize_point(
    x: Any, y: Any, image_size: tuple[int, int],
) -> tuple[int | None, int | None]:
    if x is None or y is None:
        return None, None
    img_w, img_h = image_size
    if _is_unit_float(x) and _is_unit_float(y):
        x_px = int(round(float(x) * img_w))
        y_px = int(round(float(y) * img_h))
        return clamp_to_image(x_px, y_px, image_size)
    xi, yi = as_int(x), as_int(y)
    if xi is None or yi is None:
        return None, None
    return model_point_to_image(xi, yi, image_size)


def extract_win_search_text(step: dict) -> str:
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
        "notepad", "chrome", "edge", "firefox", "explorer", "calculator",
        "paint", "word", "excel", "powershell", "cmd",
    ):
        if app in desc_lower:
            return app
    return ""


def normalize_step_dict(step: dict, image_size: tuple[int, int]) -> dict:
    normalized = dict(step)
    action = str(normalized.get("action", "")).upper()
    normalized["action"] = action

    if action == "WIN_SEARCH" and not str(normalized.get("text") or "").strip():
        normalized["text"] = extract_win_search_text(normalized)

    if action == "NAVIGATE" and not str(normalized.get("url") or "").strip():
        for key in ("url", "text", "query"):
            if str(normalized.get(key) or "").strip():
                normalized["url"] = str(normalized[key]).strip()
                break

    if action == "KNOWLEDGE_SEARCH" and not str(normalized.get("query") or "").strip():
        for key in ("query", "text", "search"):
            if str(normalized.get(key) or "").strip():
                normalized["query"] = str(normalized[key]).strip()
                break

    x, y = _extract_pair(
        normalized, "coordinates", "coordinate", "position", "point", "click", "location",
    )
    if x is None:
        x = normalized.get("x")
    if y is None:
        y = normalized.get("y")
    x, y = _normalize_point(x, y, image_size)
    if x is not None and y is not None:
        normalized["x"], normalized["y"] = x, y

    x2, y2 = _extract_pair(normalized, "end", "end_position", "target")
    if x2 is None:
        x2 = normalized.get("x2")
    if y2 is None:
        y2 = normalized.get("y2")
    x2, y2 = _normalize_point(x2, y2, image_size)
    if x2 is not None and y2 is not None:
        normalized["x2"], normalized["y2"] = x2, y2

    return normalized


def prepare_action_for_execution(
    step: dict | ActionStep,
    image_size: tuple[int, int],
    native_size: tuple[int, int],
) -> ActionStep:
    raw = step.to_dict() if isinstance(step, ActionStep) else dict(step)
    # Preserve internal keys from ActionStep.extras
    if isinstance(step, ActionStep):
        raw.update(step.extras)

    normalized = normalize_step_dict(raw, image_size)

    if normalized.get("x") is not None and normalized.get("y") is not None:
        normalized["_model_x"] = normalized["x"]
        normalized["_model_y"] = normalized["y"]
        nx, ny = image_to_native(
            int(normalized["x"]), int(normalized["y"]), image_size, native_size,
        )
        normalized["x"], normalized["y"] = nx, ny

    if normalized.get("x2") is not None and normalized.get("y2") is not None:
        nx2, ny2 = image_to_native(
            int(normalized["x2"]), int(normalized["y2"]), image_size, native_size,
        )
        normalized["x2"], normalized["y2"] = nx2, ny2

    return ActionStep.from_dict(normalized)
