"""Ollama client for the local vision model (qwen2.5vl)."""

from __future__ import annotations

import json

import httpx

from friday.config import (
    MODEL_KEEP_ALIVE,
    MODEL_NAME,
    MODEL_NUM_CTX,
    MODEL_NUM_PREDICT,
    MODEL_TEMPERATURE,
    MODEL_THINK,
    MODEL_TOP_P,
    OLLAMA_CHAT_URL,
    OVERLAY_ENABLED,
)
from friday.models.parser import ACTION_DELIMITER, parse_reasoning_response, synthesize_plan_from_partial
from friday.ui.events import emit

if OVERLAY_ENABLED:
    from friday.ui import overlay

_THINKING_MODEL_PREFIXES = (
    "qwen3", "qwen3.5", "deepseek-r1", "deepseek-r1:", "gpt-oss",
)


def is_thinking_model(model_name: str | None = None) -> bool:
    name = (model_name or MODEL_NAME).lower()
    return any(name.startswith(p) for p in _THINKING_MODEL_PREFIXES)


def _parse_keep_alive() -> int | str:
    try:
        return int(MODEL_KEEP_ALIVE)
    except ValueError:
        return MODEL_KEEP_ALIVE


def _extract_chat_tokens(chunk: dict) -> tuple[str, str]:
    thinking = chunk.get("thinking") or ""
    message = chunk.get("message")
    content = ""
    if isinstance(message, dict):
        thinking = thinking or message.get("thinking") or ""
        content = message.get("content") or ""
    content = content or chunk.get("response") or ""
    return str(thinking), str(content)


def _stream_chat(
    messages: list[dict],
    *,
    format_json: bool = False,
    reasoning_mode: bool = False,
) -> tuple[str, str]:
    payload: dict = {
        "model": MODEL_NAME,
        "messages": messages,
        "stream": True,
        "keep_alive": _parse_keep_alive(),
        "options": {
            "num_predict": MODEL_NUM_PREDICT,
            "num_ctx": MODEL_NUM_CTX,
            # Override model-card sampling: action JSON must be near-deterministic.
            "temperature": MODEL_TEMPERATURE,
            "top_p": MODEL_TOP_P,
            "presence_penalty": 0.0,
            "repeat_penalty": 1.05,
        },
    }
    if format_json:
        payload["format"] = "json"
    if is_thinking_model():
        payload["think"] = MODEL_THINK in ("1", "true", "yes")

    if OVERLAY_ENABLED:
        overlay.set_status("thinking")
        if reasoning_mode:
            overlay.clear_thinking()
    if reasoning_mode:
        emit("thinking_clear")

    accumulated = ""
    native_thinking = ""
    reasoning_shown = 0

    def _push_reasoning() -> None:
        nonlocal reasoning_shown
        if not reasoning_mode:
            return
        if ACTION_DELIMITER in accumulated:
            end = accumulated.index(ACTION_DELIMITER)
            chunk = accumulated[reasoning_shown:end]
        else:
            chunk = accumulated[reasoning_shown:]
        if chunk:
            if OVERLAY_ENABLED:
                overlay.push_thinking(chunk)
            emit("thinking_token", token=chunk)
            reasoning_shown += len(chunk)

    try:
        with httpx.stream("POST", OLLAMA_CHAT_URL, json=payload, timeout=180.0) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue

                thinking_tok, content_tok = _extract_chat_tokens(chunk)
                if thinking_tok:
                    native_thinking += thinking_tok
                if content_tok:
                    accumulated += content_tok
                    if reasoning_mode:
                        _push_reasoning()

                if chunk.get("done"):
                    break
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Ollama unreachable: {exc}") from exc

    if OVERLAY_ENABLED:
        overlay.set_status("running")

    if not accumulated.strip() and native_thinking.strip():
        accumulated = native_thinking

    return accumulated, native_thinking


def query_model_text(
    prompt: str,
    *,
    format_json: bool = False,
    reasoning_mode: bool = False,
) -> dict:
    messages = [{"role": "user", "content": prompt}]
    try:
        accumulated, _ = _stream_chat(
            messages, format_json=format_json, reasoning_mode=reasoning_mode,
        )
    except RuntimeError as exc:
        print(f"[Model Error] {exc}")
        return {"routing": "FALLBACK_TO_CLOUD", "reason": str(exc), "steps": []}

    if not accumulated.strip():
        return {"routing": "FALLBACK_TO_CLOUD", "reason": "Empty response.", "steps": []}

    if reasoning_mode or format_json:
        try:
            reasoning, plan = parse_reasoning_response(accumulated)
            if reasoning and OVERLAY_ENABLED:
                overlay.set_thinking(reasoning)
            if reasoning:
                emit("thinking_set", text=reasoning)
            return plan
        except json.JSONDecodeError as exc:
            return {"routing": "FALLBACK_TO_CLOUD", "reason": str(exc), "steps": []}

    return {"message": accumulated.strip(), "raw": accumulated.strip()}


_AIM_VERIFY_PROMPT = """You verify desktop automation click targets from a live screenshot.

The crosshair is drawn directly on this screenshot (yellow/orange = aim, cyan = adjust).

Target element: {description}
Planned action: {action}
Crosshair center ({coord_note}): ({image_x}, {image_y})
Attempt: {attempt}

Steps (do them in order — do NOT assume the aim is correct):
1. Look at the exact pixel under the crosshair center and name the UI element there.
2. verified=true ONLY if that element is the intended target. If the crosshair is on
   empty space, a different button, another window, or merely NEAR the target, verified=false.
3. If verified=false and the correct target IS visible, give the coordinates of its center.

Ignore the Friday overlay panel (top-right dark box) and any Task Manager / Ollama windows.

Reply with ONLY JSON:
{{"element_under_crosshair": "<what is actually there>", "verified": true|false, "x": <int|null>, "y": <int|null>, "reason": "<brief>"}}

Coordinates must be {coord_note}. If unsure of the correct target, use null for x and y."""


def query_aim_verification(
    *,
    target_description: str,
    action: str,
    image_x: int,
    image_y: int,
    image_size: tuple[int, int],
    frame_b64: str,
    attempt: int = 1,
) -> dict:
    """image_x/image_y and the returned x/y are in the MODEL's coordinate space."""
    from friday.actions.coordinates import uses_grid_coords

    iw, ih = image_size
    if uses_grid_coords():
        coord_note = "integers on a 0-1000 grid: (0,0) top-left, (1000,1000) bottom-right"
    else:
        coord_note = f"pixels of this {iw}x{ih} image"
    prompt = _AIM_VERIFY_PROMPT.format(
        description=target_description[:200],
        action=action,
        image_x=image_x,
        image_y=image_y,
        coord_note=coord_note,
        attempt=attempt,
    )
    messages = [{"role": "user", "content": prompt, "images": [frame_b64]}]

    if OVERLAY_ENABLED:
        overlay.set_status("verifying")

    try:
        accumulated, _ = _stream_chat(messages, format_json=True, reasoning_mode=False)
    except RuntimeError as exc:
        print(f"[Aim Verify] Model error: {exc}")
        return {"verified": False, "reason": str(exc)}

    if not accumulated.strip():
        return {"verified": False, "reason": "Empty verification response."}

    try:
        data = json.loads(accumulated.strip())
    except json.JSONDecodeError:
        start = accumulated.find("{")
        end = accumulated.rfind("}")
        if start >= 0 and end > start:
            try:
                data = json.loads(accumulated[start:end + 1])
            except json.JSONDecodeError:
                return {"verified": False, "reason": "Could not parse verification JSON."}
        else:
            return {"verified": False, "reason": "Could not parse verification JSON."}

    result = {
        "verified": bool(data.get("verified")),
        "reason": str(data.get("reason") or ""),
    }
    x, y = data.get("x"), data.get("y")
    if x is not None and y is not None:
        try:
            result["x"] = int(x)
            result["y"] = int(y)
        except (TypeError, ValueError):
            pass
    return result


def query_model_vision(
    prompt: str,
    *,
    frame_b64_list: list[str] | None = None,
    video_b64: str | None = None,
    reasoning_mode: bool = True,
) -> dict:
    if not video_b64 and not frame_b64_list:
        return {"routing": "FALLBACK_TO_CLOUD", "reason": "No vision input.", "steps": []}

    user_msg: dict = {"role": "user", "content": prompt}
    if video_b64:
        user_msg["videos"] = [video_b64]
    else:
        user_msg["images"] = frame_b64_list or []

    if OVERLAY_ENABLED and reasoning_mode:
        overlay.clear_thinking()
    if reasoning_mode:
        emit("thinking_clear")

    try:
        accumulated, _ = _stream_chat([user_msg], reasoning_mode=reasoning_mode)
    except RuntimeError as exc:
        print(f"[Model Error] {exc}")
        return {"routing": "FALLBACK_TO_CLOUD", "reason": str(exc), "steps": []}

    if not accumulated.strip():
        return {"routing": "FALLBACK_TO_CLOUD", "reason": "Empty response.", "steps": []}

    try:
        reasoning, plan = parse_reasoning_response(accumulated)
        if reasoning and OVERLAY_ENABLED:
            overlay.set_thinking(reasoning)
        if reasoning:
            emit("thinking_set", text=reasoning)
        if not plan.get("steps"):
            synthesized = synthesize_plan_from_partial(accumulated)
            if synthesized:
                print("[Model] Recovered plan via prose synthesis (ALLOW_PROSE_SYNTHESIS=true).")
                plan = synthesized
            else:
                print("[Model] Parsed JSON but no actionable step.")
                print(f"  Raw (first 500): {accumulated[:500]!r}")
                return {
                    "routing": "FALLBACK_TO_CLOUD",
                    "reason": "Model returned no steps.",
                    "message": plan.get("message", ""),
                    "steps": [],
                }
        steps = plan.get("steps") or []
        if steps:
            act = str(steps[0].get("action", "")).upper()
            s0 = steps[0]
            if act in ("CLICK", "DOUBLE_CLICK", "RIGHT_CLICK", "HOVER", "SCROLL", "MOUSE_MOVE"):
                if s0.get("x") is None or s0.get("y") is None:
                    print(f"[Model] {act} step missing coordinates after enrichment.")
                    return {
                        "routing": "FALLBACK_TO_CLOUD",
                        "reason": f"{act} missing x/y coordinates.",
                        "steps": [],
                    }
        return plan
    except json.JSONDecodeError as exc:
        print(f"[Model Error] JSON parse failed: {exc}")
        print(f"  Raw (first 300): {accumulated[:300]!r}")
        return {"routing": "FALLBACK_TO_CLOUD", "reason": str(exc), "steps": []}
