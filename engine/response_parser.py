"""Parse model responses that separate reasoning prose from action JSON."""

from __future__ import annotations

import json
from typing import Any

ACTION_DELIMITER = "---ACTION---"


def extract_json(raw: str) -> dict:
    """
    Extract the first complete JSON object from a potentially noisy string.
    Handles models that wrap output in markdown fences or add prose before/after.
    """
    raw = raw.strip()

    for fence in ("```json", "```"):
        if raw.startswith(fence):
            raw = raw[len(fence):]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()
            break

    start = raw.find("{")
    if start == -1:
        raise json.JSONDecodeError("No JSON object found", raw, 0)

    depth = 0
    in_string = False
    escape_next = False

    for i, ch in enumerate(raw[start:], start=start):
        if escape_next:
            escape_next = False
            continue
        if ch == "\\" and in_string:
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(raw[start : i + 1])

    raise json.JSONDecodeError("Unterminated JSON object", raw, len(raw))


def parse_reasoning_response(raw: str) -> tuple[str, dict[str, Any]]:
    """Split optional reasoning prose from the trailing JSON action object."""
    raw = raw.strip()
    if not raw:
        raise json.JSONDecodeError("Empty response", raw, 0)

    if ACTION_DELIMITER in raw:
        reasoning, _, json_part = raw.partition(ACTION_DELIMITER)
        return reasoning.strip(), extract_json(json_part.strip())

    return "", extract_json(raw)
