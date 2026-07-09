"""Parse VLM responses that separate reasoning from action JSON."""

from __future__ import annotations

import json
import re
from typing import Any, Iterator

from friday.config import ALLOW_PROSE_SYNTHESIS

ACTION_DELIMITER = "---ACTION---"

_ACTION_PREFIXES = (
    "CLICK", "DOUBLE_CLICK", "RIGHT_CLICK", "MIDDLE_CLICK", "HOVER",
    "WIN_SEARCH", "TYPE", "PRESS_KEY", "HOTKEY", "SCROLL", "WAIT",
    "NAVIGATE", "KNOWLEDGE_SEARCH", "COMPLETE",
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
        "observation": message,
        "steps": [{
            "action": action,
            "x": x,
            "y": y,
            "description": message or f"{action} target",
            "risky": False,
        }],
        "needs_knowledge": False,
    }


def synthesize_plan_from_partial(text: str, reasoning: str = "") -> dict[str, Any] | None:
    """Best-effort recovery from malformed model output. Disabled in production by default."""
    if not ALLOW_PROSE_SYNTHESIS:
        return None

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
        }

    if "KNOWLEDGE_SEARCH" in upper:
        quoted = re.search(r"""['"]([^'"]+)['"]""", text)
        query = quoted.group(1) if quoted else "help"
        return {
            "message": f"Search knowledge: {query}",
            "needs_knowledge": True,
            "knowledge_query": query,
            "steps": [{
                "action": "KNOWLEDGE_SEARCH",
                "query": query,
                "description": f"Look up: {query}",
                "risky": False,
            }],
        }

    if "WAIT" in upper:
        return {
            "message": "Wait for UI",
            "steps": [{"action": "WAIT", "duration": 1.0, "description": "Wait", "risky": False}],
        }

    if "COMPLETE" in upper:
        return {
            "message": "Task complete",
            "completion_evidence": "prose synthesis (debug)",
            "steps": [{"action": "COMPLETE", "description": "Done", "risky": False}],
        }

    return None


_ACTION_TOKEN_RE: "re.Pattern[str] | None" = None


def _action_token_pattern() -> "re.Pattern[str]":
    global _ACTION_TOKEN_RE
    if _ACTION_TOKEN_RE is None:
        try:
            from friday.actions.catalog import ALL_ACTION_NAMES
            names = list(ALL_ACTION_NAMES)
        except Exception:
            names = list(_ACTION_PREFIXES)
        # Longest first so DOUBLE_CLICK matches before CLICK.
        names.sort(key=len, reverse=True)
        pattern = r"\b(" + "|".join(re.escape(n) for n in names) + r")\b"
        _ACTION_TOKEN_RE = re.compile(pattern, re.IGNORECASE)
    return _ACTION_TOKEN_RE


def parse_action_directive(action_part: str) -> dict[str, Any] | None:
    """
    Deterministically parse the '<ACTION_NAME> {args}' form that VLMs emit,
    e.g. `CLICK {"x": 1056, "y": 487}` or `TYPE {"text": "hello"}`.

    This is NOT prose synthesis: it only recovers a step when the model
    supplied a real action token together with the required arguments, so it
    never fabricates coordinates or text.
    """
    text = _strip_fences(action_part).strip()
    if not text:
        return None

    # Prefer a well-formed object that already declares steps/action.
    objs = list(_iter_json_objects(text))
    for obj in reversed(objs):
        if obj.get("steps") or obj.get("action"):
            return _normalize_plan_shape(obj)

    match = _action_token_pattern().search(text)
    if not match:
        return None
    action = match.group(1).upper()

    args: dict[str, Any] = {}
    tail = text[match.end():]
    for obj in _iter_json_objects(tail):
        args = obj
        break
    if not args:
        coord = re.search(r"\(?\s*(-?\d{1,5})\s*[,x]\s*(-?\d{1,5})\s*\)?", tail)
        if coord:
            args = {"x": int(coord.group(1)), "y": int(coord.group(2))}

    step: dict[str, Any] = {"action": action, "risky": False}
    step.update(args)

    # Reject fabricated actions missing their required payload.
    try:
        from friday.actions.catalog import COORD_ACTIONS
    except Exception:
        COORD_ACTIONS = frozenset({"CLICK", "DOUBLE_CLICK", "RIGHT_CLICK", "HOVER", "SCROLL"})
    if action in COORD_ACTIONS and (step.get("x") is None or step.get("y") is None):
        return None
    if action in ("TYPE", "PASTE") and not str(step.get("text") or "").strip():
        return None

    return {"message": "", "steps": [step]}


def _normalize_plan_shape(plan: dict[str, Any]) -> dict[str, Any]:
    """Accept top-level action objects; do not invent coordinates from prose."""
    if not plan.get("steps") and "x" in plan and "y" in plan and plan.get("action"):
        return _plan_from_click(
            int(plan["x"]), int(plan["y"]),
            str(plan.get("action", "CLICK")).upper(),
            str(plan.get("message", "")),
        )

    steps = plan.get("steps")
    if not isinstance(steps, list) and plan.get("action"):
        return {
            "message": plan.get("message", ""),
            "observation": plan.get("observation", ""),
            "last_action_result": plan.get("last_action_result"),
            "completion_evidence": plan.get("completion_evidence"),
            "needs_knowledge": plan.get("needs_knowledge", False),
            "knowledge_query": plan.get("knowledge_query"),
            "steps": [plan],
        }
    return plan


def extract_json(raw: str) -> dict[str, Any]:
    objects = list(_iter_json_objects(raw))

    for obj in reversed(objects):
        if obj.get("steps") or obj.get("action") or obj.get("phases"):
            return _normalize_plan_shape(obj)

    # Model commonly emits '<ACTION> {args}' (e.g. CLICK {"x":..,"y":..}).
    # This is a real action + payload, so parse it deterministically.
    directive = parse_action_directive(raw)
    if directive and directive.get("steps"):
        return directive

    if len(objects) == 1 and "x" in objects[0] and "y" in objects[0]:
        if ALLOW_PROSE_SYNTHESIS:
            return _plan_from_click(int(objects[0]["x"]), int(objects[0]["y"]))

    synthesized = synthesize_plan_from_partial(raw)
    if synthesized:
        return synthesized

    if objects:
        return _normalize_plan_shape(objects[-1])

    raise json.JSONDecodeError("No JSON object found", raw, 0)


def parse_reasoning_response(raw: str) -> tuple[str, dict[str, Any]]:
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
        if not plan.get("steps") and not plan.get("action"):
            plan = synthesize_plan_from_partial(action_part, reasoning) or plan
        return reasoning, _normalize_plan_shape(plan)

    return "", extract_json(raw)
