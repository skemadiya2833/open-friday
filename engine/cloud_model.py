import base64
import json
import os
from config import CLOUD_PROVIDER, GEMINI_API_KEY, OPENAI_API_KEY
from engine.local_model import SYSTEM_PROMPT


def query_cloud_model(
    objective: str,
    base64_image: str | None = None,
    system_prompt: str | None = None,
    native_size: tuple[int, int] | None = None,
    image_size: tuple[int, int] | None = None,
) -> dict:
    """Routes to the configured cloud provider."""
    prompt = system_prompt or SYSTEM_PROMPT
    screen_line = ""
    if native_size and image_size:
        screen_line = (
            f"\nMonitor: {native_size[0]}x{native_size[1]}. "
            f"Screenshot: {image_size[0]}x{image_size[1]}."
        )
    full_prompt = f"{prompt}{screen_line}"
    if CLOUD_PROVIDER == "gemini":
        return _query_gemini(objective, base64_image, full_prompt)
    elif CLOUD_PROVIDER == "openai":
        return _query_openai(objective, base64_image, full_prompt)
    else:
        raise ValueError(f"Unknown CLOUD_PROVIDER: {CLOUD_PROVIDER}")


def _query_gemini(objective: str, base64_image: str | None, system_prompt: str) -> dict:
    try:
        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)

        model = genai.GenerativeModel("gemini-1.5-pro-latest")

        prompt = f"{system_prompt}\n\nUser Objective: {objective}"
        parts: list = [prompt]
        if base64_image:
            parts.append({"mime_type": "image/png", "data": base64_image})
        response = model.generate_content(parts)

        raw = response.text.strip().strip("```json").strip("```").strip()
        return json.loads(raw)

    except Exception as e:
        print(f"[Gemini Error] {e}")
        return {"steps": [], "message": f"Cloud model error: {e}"}


def _query_openai(objective: str, base64_image: str | None, system_prompt: str) -> dict:
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
        raw = raw.strip().strip("```json").strip("```").strip()
        return json.loads(raw)

    except Exception as e:
        print(f"[OpenAI Error] {e}")
        return {"steps": [], "message": f"Cloud model error: {e}"}