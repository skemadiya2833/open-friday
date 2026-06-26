import base64
import json
import os
from config import CLOUD_PROVIDER, GEMINI_API_KEY, OPENAI_API_KEY, OVERLAY_ENABLED
from engine.local_model import SYSTEM_PROMPT
from engine.response_parser import parse_reasoning_response

if OVERLAY_ENABLED:
    from engine import overlay

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
    native_size: tuple[int, int] | None = None,
    image_size: tuple[int, int] | None = None,
    *,
    reasoning_mode: bool = False,
) -> dict:
    """Routes to the configured cloud provider."""
    if not cloud_api_configured():
        msg = (
            f"Cloud provider '{CLOUD_PROVIDER}' has no valid API key. "
            f"Add your key to .env or fix the local model."
        )
        print(f"[Cloud Model] {msg}")
        return {"steps": [], "message": msg}

    prompt = system_prompt or SYSTEM_PROMPT
    screen_line = ""
    if native_size and image_size:
        screen_line = (
            f"\nMonitor: {native_size[0]}x{native_size[1]}. "
            f"Screenshot: {image_size[0]}x{image_size[1]}."
        )
    full_prompt = f"{prompt}{screen_line}"
    if CLOUD_PROVIDER == "gemini":
        return _query_gemini(objective, base64_image, full_prompt, reasoning_mode)
    elif CLOUD_PROVIDER == "openai":
        return _query_openai(objective, base64_image, full_prompt, reasoning_mode)
    else:
        raise ValueError(f"Unknown CLOUD_PROVIDER: {CLOUD_PROVIDER}")


def _apply_reasoning(raw: str, reasoning_mode: bool) -> dict:
    try:
        reasoning, plan = parse_reasoning_response(raw)
    except json.JSONDecodeError as exc:
        print(f"[Cloud Model Error] JSON parse failed: {exc}")
        return {"steps": [], "message": f"Cloud model error: {exc}"}

    if reasoning_mode and reasoning and OVERLAY_ENABLED:
        overlay.clear_thinking()
        overlay.set_thinking(reasoning)
    return plan


def _query_gemini(
    objective: str,
    base64_image: str | None,
    system_prompt: str,
    reasoning_mode: bool,
) -> dict:
    try:
        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)

        model = genai.GenerativeModel("gemini-1.5-pro-latest")

        prompt = f"{system_prompt}\n\nUser Objective: {objective}"
        parts: list = [prompt]
        if base64_image:
            parts.append({"mime_type": "image/png", "data": base64_image})
        response = model.generate_content(parts)

        raw = response.text.strip()
        return _apply_reasoning(raw, reasoning_mode)

    except Exception as e:
        print(f"[Gemini Error] {e}")
        return {"steps": [], "message": f"Cloud model error: {e}"}


def _query_openai(
    objective: str,
    base64_image: str | None,
    system_prompt: str,
    reasoning_mode: bool,
) -> dict:
    try:
        import httpx
        headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json"
        }

        content: list = [
            {"type": "text", "text": f"{system_prompt}\n\nUser Objective: {objective}"},
        ]
        if base64_image:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{base64_image}"},
                }
            )

        payload = {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": content}],
            "max_tokens": 1500
        }

        response = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=60.0
        )
        response.raise_for_status()

        raw = response.json()["choices"][0]["message"]["content"]
        return _apply_reasoning(raw.strip(), reasoning_mode)

    except Exception as e:
        print(f"[OpenAI Error] {e}")
        return {"steps": [], "message": f"Cloud model error: {e}"}
