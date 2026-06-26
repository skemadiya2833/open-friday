import json

import httpx

from config import OLLAMA_API_URL, LOCAL_MODEL_NAME, OVERLAY_ENABLED
from engine.response_parser import ACTION_DELIMITER, parse_reasoning_response

if OVERLAY_ENABLED:
    from engine import overlay

# Models that emit chain-of-thought in Ollama's separate `thinking` field.
# Friday uses its own reasoning format, so disable native thinking on /api/generate.
_THINKING_MODEL_PREFIXES = (
    "qwen3",
    "qwen3.5",
    "deepseek-r1",
    "deepseek-r1:",
    "gpt-oss",
)

SYSTEM_PROMPT = """You are Friday, an autonomous desktop automation agent.
Analyze the screenshot and the user's task. Respond ONLY with a valid JSON object.

{
  "message": "What you are about to do, in plain language.",
  "routing": "LOCAL",
  "reason": "Brief explanation of routing decision.",
  "steps": [
    {
      "action": "ACTION_NAME",
      "description": "What this step does.",
      "x": null,
      "y": null,
      "text": null,
      "key": null,
      "keys": null,
      "direction": null,
      "amount": null,
      "duration": null,
      "button": "left",
      "risky": false
    }
  ]
}

RULES:
- Return ONLY raw JSON. No markdown fences, no preamble, no prose outside the object.
- x and y are absolute pixel coordinates in screenshot image space.
- Mark risky: true for DELETE, FORMAT, or any irreversible destructive action.
- Insert a SCREENSHOT step whenever you need to reassess screen state before continuing.
"""


def is_thinking_model(model_name: str | None = None) -> bool:
    name = (model_name or LOCAL_MODEL_NAME).lower()
    return any(name.startswith(prefix) for prefix in _THINKING_MODEL_PREFIXES)


def _extract_stream_tokens(chunk: dict) -> tuple[str, str]:
    """Return (thinking_tokens, response_tokens) from an Ollama stream chunk."""
    thinking = chunk.get("thinking") or ""
    response = chunk.get("response") or ""

    message = chunk.get("message")
    if isinstance(message, dict):
        thinking = thinking or message.get("thinking") or ""
        response = response or message.get("content") or ""

    return str(thinking), str(response)


def query_local_model(
    objective: str,
    base64_image: str | None = None,
    system_prompt: str | None = None,
    native_size: tuple[int, int] | None = None,
    image_size: tuple[int, int] | None = None,
    *,
    reasoning_mode: bool = False,
) -> dict:
    """
    Send objective and optional screenshot to the local Ollama VLM.

    With reasoning_mode=True, the model streams plain-English reasoning to the
    overlay first, then emits ---ACTION--- followed by JSON.
    """
    prompt_text = system_prompt or SYSTEM_PROMPT

    screen_line = ""
    if native_size and image_size:
        screen_line = (
            f"\nMonitor resolution: {native_size[0]}x{native_size[1]}. "
            f"Screenshot image size: {image_size[0]}x{image_size[1]}. "
            f"ALL coordinates must be in screenshot image space."
        )

    full_prompt = f"{prompt_text}{screen_line}\n\nUser Objective: {objective}"

    payload: dict = {
        "model": LOCAL_MODEL_NAME,
        "prompt": full_prompt,
        "stream": True,
        "options": {"num_predict": 2048},
    }
    if not reasoning_mode:
        payload["format"] = "json"

    # Qwen3+ thinking models put all tokens in `thinking` and leave `response`
    # empty unless native thinking is disabled. Friday has its own reasoning format.
    if is_thinking_model():
        payload["think"] = False

    if base64_image:
        payload["images"] = [base64_image]

    if OVERLAY_ENABLED:
        overlay.set_status("thinking")
        overlay.clear_thinking()

    accumulated = ""
    native_thinking = ""
    reasoning_shown = 0

    def _stream_custom_reasoning() -> None:
        nonlocal reasoning_shown
        if not OVERLAY_ENABLED or not reasoning_mode:
            return
        if ACTION_DELIMITER in accumulated:
            end = accumulated.index(ACTION_DELIMITER)
            chunk = accumulated[reasoning_shown:end]
        else:
            chunk = accumulated[reasoning_shown:]
        if chunk:
            overlay.push_thinking(chunk)
            reasoning_shown += len(chunk)

    try:
        with httpx.stream(
            "POST",
            OLLAMA_API_URL,
            json=payload,
            timeout=120.0,
        ) as response:
            response.raise_for_status()

            for line in response.iter_lines():
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue

                thinking_tok, response_tok = _extract_stream_tokens(chunk)
                if thinking_tok:
                    native_thinking += thinking_tok
                    if OVERLAY_ENABLED and not reasoning_mode:
                        overlay.push_thinking(thinking_tok)

                if response_tok:
                    accumulated += response_tok
                    if reasoning_mode:
                        _stream_custom_reasoning()
                    elif OVERLAY_ENABLED:
                        overlay.push_thinking(response_tok)

                if chunk.get("done"):
                    break

    except httpx.HTTPError as exc:
        print(f"[Local Model Error] {exc}")
        if OVERLAY_ENABLED:
            overlay.set_status("idle")
        return {
            "routing": "FALLBACK_TO_CLOUD",
            "reason": f"Local model unreachable: {exc}",
            "steps": [],
        }

    if OVERLAY_ENABLED:
        overlay.set_status("running")

    if not accumulated.strip() and native_thinking.strip():
        print(
            "[Local Model] Model returned thinking trace but no response text. "
            "If this persists, try a non-thinking model or update Ollama."
        )
        accumulated = native_thinking

    if not accumulated.strip():
        return {
            "routing": "FALLBACK_TO_CLOUD",
            "reason": "Empty response from local model.",
            "steps": [],
        }

    try:
        if reasoning_mode:
            reasoning, plan = parse_reasoning_response(accumulated)
            if reasoning and OVERLAY_ENABLED:
                overlay.set_thinking(reasoning)
            return plan
        return parse_reasoning_response(accumulated)[1]
    except json.JSONDecodeError as exc:
        print(f"[Local Model Error] JSON parse failed: {exc}")
        print(f"  Raw response (first 300 chars): {accumulated[:300]!r}")
        return {
            "routing": "FALLBACK_TO_CLOUD",
            "reason": f"Malformed local model output: {exc}",
            "steps": [],
        }
