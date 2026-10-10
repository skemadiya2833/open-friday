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


_FALLBACK_GEMINI = "gemini-2.5-flash"
_gemini_model: str | None = None


def pick_gemini_model(names: list[str]) -> str | None:
    """Best general vision-capable stable Flash model from a models list (pure; unit-tested).

    Prefers the highest-versioned ``gemini-N[.M]-flash`` that is not lite/preview/experimental/image/tts/live,
    then the highest-versioned ``-pro``. Returns None when nothing suitable is listed."""
    import re

    def ver(n: str) -> tuple:
        m = re.search(r"gemini-(\d+)(?:\.(\d+))?", n)
        return (int(m.group(1)), int(m.group(2) or 0)) if m else (0, 0)

    ok = []
    for raw in names:
        n = raw.split("/")[-1]
        if not n.startswith("gemini-"):
            continue
        ok.append(n)
    for kind in ("flash", "pro"):
        c = [n for n in ok if re.fullmatch(rf"gemini-\d+(\.\d+)?-{kind}", n)]
        if c:
            return max(c, key=ver)
    return None


def discover_gemini_model(client) -> str:
    """GEMINI_MODEL wins; otherwise ask the installed google-genai client which models this key can use.
    UNVERIFIED without a real key: only ``pick_gemini_model`` is tested, with a fake listing."""
    import os

    global _gemini_model
    if os.getenv("GEMINI_MODEL"):
        return os.environ["GEMINI_MODEL"]
    if _gemini_model:
        return _gemini_model
    try:
        names = [m.name for m in client.models.list()
                 if "generateContent" in (getattr(m, "supported_actions", None) or ["generateContent"])]
        _gemini_model = pick_gemini_model(names) or _FALLBACK_GEMINI
    except Exception as e:  # noqa: BLE001
        print(f"[Gemini] model discovery failed ({e}); using {_FALLBACK_GEMINI}")
        _gemini_model = _FALLBACK_GEMINI
    return _gemini_model


def _call_gemini(prompt: str, base64_image: str | None) -> str | None:
    # google-genai (the supported SDK). API verified against google-genai 2.28.0 signatures;
    # a live call needs a real key and is UNVERIFIED. Model is configurable: the old
    # "gemini-1.5-pro-latest" is retired.
    try:
        import base64

        from google import genai
        from google.genai import types

        client = genai.Client(api_key=GEMINI_API_KEY)
        contents: list = [prompt]
        if base64_image:
            contents.insert(0, types.Part.from_bytes(data=base64.b64decode(base64_image), mime_type=_mime_type()))
        response = client.models.generate_content(model=discover_gemini_model(client), contents=contents)
        return (response.text or "").strip()
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
