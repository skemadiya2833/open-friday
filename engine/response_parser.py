"""Parse model responses that separate reasoning prose from action JSON."""

from __future__ import annotations

import json
import re
from typing import Any, Iterator

ACTION_DELIMITER = "---ACTION---"

_ACTION_PREFIXES = (
    "CLICK", "DOUBLE_CLICK", "RIGHT_CLICK", "MIDDLE_CLICK", "HOVER",
    "WIN_SEARCH", "TYPE", "PRESS_KEY", "HOTKEY", "SCROLL", "WAIT", "COMPLETE",
)


def _strip_fences(raw: str) -> str:
    raw = raw.strip()
    for fence in ("```json", "```"):
        if raw.startswith(fence):
            raw = raw[len(fence):]
            if raw.endswith("```"):
                raw = raw[:-3]
            return raw.strip()
    return raw


def _iter_json_objects(raw: str) -> Iterator[dict[str, Any]]:
    """Yield every complete top-level JSON object found in a string."""
    raw = _strip_fences(raw)
    start = 0
    while start < len(raw):
        brace = raw.find("{", start)
        if brace == -1:
            return
        depth = 0
        in_string = False
        escape_next = False
        for i, ch in enumerate(raw[brace:], start=brace):
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
                    snippet = raw[brace : i + 1]
                    try:
                        yield json.loads(snippet)
                    except json.JSONDecodeError:
                        pass
                    start = i + 1
                    break
        else:
            return


def _coords_from_prose(text: str) -> tuple[int, int, str] | None:
    """
    Parse coordinates from Qwen's common formats, including truncated output:
      CLICK {"x": 508, "y": 347}
      CLICK {"x": 500, "y": 300   (no closing brace)
    """
    for action in ("DOUBLE_CLICK", "RIGHT_CLICK", "MIDDLE_CLICK", "HOVER", "CLICK"):
        match = re.search(
            rf"{action}\s*\{{\s*\"x\"\s*:\s*(\d+)\s*,\s*\"y\"\s*:\s*(\d+)",
            text,
            re.IGNORECASE,
        )
        if match:
            return int(match.group(1)), int(match.group(2)), action.upper()

    match = re.search(
        r'(\{[^{}]*"x"\s*:\s*(\d+)[^{}]*"y"\s*:\s*(\d+)[^{}]*\})',
        text,
    )
    if match:
        try:
            data = json.loads(match.group(1))
            if data.get("x") is not None and data.get("y") is not None:
                return int(data["x"]), int(data["y"]), "CLICK"
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

    return None


def _plan_from_click(x: int, y: int, action: str = "CLICK", message: str = "") -> dict[str, Any]:
    return {
        "message": message or f"{action} at ({x}, {y})",
        "steps": [{
            "action": action,
            "x": x,
            "y": y,
            "description": message or f"{action} target",
            "risky": False,
        }],
        "phase_complete": False,
    }


def synthesize_plan_from_partial(text: str, reasoning: str = "") -> dict[str, Any] | None:
    """Build a valid plan when the model only emits a shorthand action line."""
    text = text.strip()
    if not text:
        return None

    coords = _coords_from_prose(text)
    if coords:
        x, y, action = coords
        return _plan_from_click(x, y, action, reasoning.strip()[:120])

    upper = text.upper()
    if "WIN_SEARCH" in upper or re.search(r"open\s+notepad|search.*notepad", text, re.I):
        app = "notepad"
        quoted = re.search(r"""['"]([^'"]+)['"]""", text)
        if quoted:
            app = quoted.group(1)
        return {
            "message": f"Open {app}",
            "steps": [{
                "action": "WIN_SEARCH",
                "text": app,
                "description": f"Open {app} via Windows search",
                "risky": False,
            }],
            "phase_complete": False,
        }

    if "PHASE_COMPLETE" in upper or "NO DIALOG" in upper or "SCREEN IS CLEAR" in upper:
        return {
            "message": "No dialogs blocking — advancing phase",
            "steps": [{"action": "WAIT", "duration": 0.3, "description": "Screen clear", "risky": False}],
            "phase_complete": True,
        }

    if "WAIT" in upper:
        return {
            "message": "Wait for UI",
            "steps": [{"action": "WAIT", "duration": 1.0, "description": "Wait", "risky": False}],
            "phase_complete": False,
        }

    return None


def _enrich_plan(plan: dict[str, Any], context: str) -> dict[str, Any]:
    """Fill missing fields; convert bare coordinate dicts into CLICK steps."""
    if not plan.get("steps") and "x" in plan and "y" in plan:
        return _plan_from_click(int(plan["x"]), int(plan["y"]), "CLICK", str(plan.get("message", "")))

    steps = plan.get("steps")
    if not isinstance(steps, list):
        return plan

    coord_objects = [
        o for o in _iter_json_objects(context)
        if "x" in o and "y" in o and "steps" not in o and "phases" not in o
    ]
    prose = _coords_from_prose(context)

    for step in steps:
        action = str(step.get("action", "")).upper()
        if action not in ("CLICK", "DOUBLE_CLICK", "RIGHT_CLICK", "HOVER", "SCROLL", "MIDDLE_CLICK"):
            continue
        if step.get("x") is not None and step.get("y") is not None:
            continue
        if coord_objects:
            step["x"] = coord_objects[-1].get("x")
            step["y"] = coord_objects[-1].get("y")
        elif prose:
            step["x"], step["y"], _ = prose

    return plan


def extract_json(raw: str) -> dict[str, Any]:
    """Extract the best JSON object, or synthesize from partial model output."""
    objects = list(_iter_json_objects(raw))

    for obj in reversed(objects):
        if obj.get("steps") or obj.get("phases"):
            return _enrich_plan(obj, raw)

    if len(objects) == 1 and "x" in objects[0] and "y" in objects[0]:
        return _plan_from_click(int(objects[0]["x"]), int(objects[0]["y"]))

    synthesized = synthesize_plan_from_partial(raw)
    if synthesized:
        return synthesized

    if objects:
        return _enrich_plan(objects[-1], raw)

    raise json.JSONDecodeError("No JSON object found", raw, 0)


def parse_reasoning_response(raw: str) -> tuple[str, dict[str, Any]]:
    """Split reasoning prose from the action JSON (tolerates truncated Qwen output)."""
    raw = raw.strip()
    if not raw:
        raise json.JSONDecodeError("Empty response", raw, 0)

    if ACTION_DELIMITER in raw:
        reasoning, _, action_part = raw.partition(ACTION_DELIMITER)
        reasoning = reasoning.strip()
        action_part = action_part.strip()
        try:
            plan = extract_json(action_part)
        except json.JSONDecodeError:
            plan = synthesize_plan_from_partial(action_part, reasoning)
            if not plan:
                raise
        if not plan.get("steps"):
            plan = synthesize_plan_from_partial(action_part, reasoning) or plan
        return reasoning, _enrich_plan(plan, action_part)

    return "", extract_json(raw)
