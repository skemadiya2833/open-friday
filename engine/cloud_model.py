import json

from config import CLOUD_PROVIDER, GEMINI_API_KEY, OPENAI_API_KEY, OVERLAY_ENABLED
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
    """Cloud fallback when local Qwen2.5-VL is unreachable."""
    if not cloud_api_configured():
        msg = f"Cloud provider '{CLOUD_PROVIDER}' has no valid API key."
        print(f"[Cloud Model] {msg}")
        return {"steps": [], "message": msg}

    prompt = system_prompt or objective
    if native_size and image_size:
        prompt += f"\nMonitor: {native_size[0]}x{native_size[1]}. Image: {image_size[0]}x{image_size[1]}."
    full_prompt = f"{prompt}\n\nUser Objective: {objective}"

    raw = _call_cloud(full_prompt, base64_image)
    if raw is None:
        return {"steps": [], "message": "Cloud model call failed."}

    return _apply_reasoning(raw, reasoning_mode)


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
            parts.append({"mime_type": "image/png", "data": base64_image})
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
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{base64_image}"},
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
