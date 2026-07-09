"""Cloud vision fallback when the local model is unavailable."""

from __future__ import annotations

import json

from friday.config import CLOUD_PROVIDER, GEMINI_API_KEY, OPENAI_API_KEY, OVERLAY_ENABLED, PREPROCESS_FORMAT
from friday.models.parser import parse_reasoning_response
from friday.ui.events import emit

if OVERLAY_ENABLED:
    from friday.ui import overlay

_PLACEHOLDER_KEYS = {
    "",
    "your_gemini_api_key_here",
    "your_openai_key_if_using_openai",
}


def cloud_api_configured() -> bool:
    if CLOUD_PROVIDER == "gemini":
        return bool(GEMINI_API_KEY and GEMINI_API_KEY not in _PLACEHOLDER_KEYS)
    if CLOUD_PROVIDER == "openai":
        return bool(OPENAI_API_KEY and OPENAI_API_KEY not in _PLACEHOLDER_KEYS)
    return False


def query_cloud_model(
    objective: str,
    base64_image: str | None = None,
    system_prompt: str | None = None,
    *,
    reasoning_mode: bool = False,
) -> dict:
    if not cloud_api_configured():
        msg = f"Cloud provider '{CLOUD_PROVIDER}' has no valid API key."
        print(f"[Cloud Model] {msg}")
        return {"steps": [], "message": msg}

    # Prefer an explicit system/decision prompt; fall back to objective alone.
    if system_prompt:
        full_prompt = system_prompt
        if objective and objective not in system_prompt:
            full_prompt = f"{system_prompt}\n\nUser Objective: {objective}"
    else:
        full_prompt = f"User Objective: {objective}"

    raw = _call_cloud(full_prompt, base64_image)
    if raw is None:
        return {"steps": [], "message": "Cloud model call failed."}

    try:
        reasoning, plan = parse_reasoning_response(raw)
    except json.JSONDecodeError as exc:
        print(f"[Cloud Model Error] JSON parse failed: {exc}")
        return {"steps": [], "message": f"Cloud model error: {exc}"}

    if reasoning_mode and reasoning:
        if OVERLAY_ENABLED:
            overlay.clear_thinking()
            overlay.set_thinking(reasoning)
        emit("thinking_set", text=reasoning)

    steps = plan.get("steps") or []
    if steps:
        act = str(steps[0].get("action", "")).upper()
        s0 = steps[0]
        if act in ("CLICK", "DOUBLE_CLICK", "RIGHT_CLICK", "HOVER", "SCROLL", "MOUSE_MOVE"):
            if s0.get("x") is None or s0.get("y") is None:
                return {
                    "steps": [],
                    "message": f"{act} missing x/y coordinates.",
                    "reason": f"{act} missing x/y coordinates.",
                }
    return plan


def _mime_type() -> str:
    return "image/jpeg" if PREPROCESS_FORMAT == "jpeg" else "image/png"


def _call_cloud(prompt: str, base64_image: str | None) -> str | None:
    if CLOUD_PROVIDER == "gemini":
        return _call_gemini(prompt, base64_image)
    if CLOUD_PROVIDER == "openai":
        return _call_openai(prompt, base64_image)
    raise ValueError(f"Unknown CLOUD_PROVIDER: {CLOUD_PROVIDER}")


def _call_gemini(prompt: str, base64_image: str | None) -> str | None:
    try:
        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-1.5-pro-latest")
        parts: list = [prompt]
        if base64_image:
            parts.append({"mime_type": _mime_type(), "data": base64_image})
        response = model.generate_content(parts)
        return response.text.strip()
    except Exception as e:
        print(f"[Gemini Error] {e}")
        return None


def _call_openai(prompt: str, base64_image: str | None) -> str | None:
    try:
        import httpx
        headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        }
        content: list = [{"type": "text", "text": prompt}]
        if base64_image:
            mime = _mime_type()
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{base64_image}"},
            })
        payload = {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": content}],
            "max_tokens": 1500,
        }
        response = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers=headers, json=payload, timeout=60.0,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"[OpenAI Error] {e}")
        return None
