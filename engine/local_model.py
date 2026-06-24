import httpx
import json
from config import OLLAMA_API_URL, LOCAL_MODEL_NAME

SYSTEM_PROMPT = """You are Friday, an autonomous desktop automation agent.
Analyze the screenshot and the user's task. Respond ONLY with a valid JSON object.

{
  "message": "What you are about to do, in plain language.",
  "routing": "LOCAL" or "FALLBACK_TO_CLOUD",
  "reason": "Brief explanation of routing decision.",
  "steps": [
    {
      "action": "CLICK" | "TYPE" | "PASTE" | "SCROLL" | "SEARCH" | "SCREENSHOT" | "WAIT" | "COMPLETE" | "DELETE" | "DRAG",
      "description": "What this step does.",
      "x": null_or_integer,
      "y": null_or_integer,
      "text": null_or_string,
      "direction": null | "up" | "down",
      "risky": true | false
    }
  ]
}

RULES:
- x and y must be absolute pixel coordinates on screen when action is CLICK, HOVER, or DRAG.
- text must contain the full string to type or paste when action is TYPE or PASTE.
- Insert a SCREENSHOT step whenever you need to reassess the screen state before continuing.
- Mark risky as true for any DELETE, FORMAT, EXECUTE_SCRIPT, or irreversible browser state change.
- Never wrap output in markdown. Raw JSON only.
"""


def query_local_model(
    objective: str,
    base64_image: str,
    system_prompt: str | None = None,
    native_size: tuple[int, int] | None = None,
    image_size: tuple[int, int] | None = None,
) -> dict:
    """Sends screenshot + objective to local Ollama VLM."""
    prompt = system_prompt or SYSTEM_PROMPT
    screen_line = ""
    if native_size and image_size:
        screen_line = (
            f"\nMonitor: {native_size[0]}x{native_size[1]}. "
            f"Screenshot: {image_size[0]}x{image_size[1]}."
        )
    payload = {
        "model": LOCAL_MODEL_NAME,
        "prompt": f"{prompt}{screen_line}\n\nUser Objective: {objective}",
        "images": [base64_image],
        "stream": False,
        "format": "json"
    }

    try:
        response = httpx.post(OLLAMA_API_URL, json=payload, timeout=90.0)
        response.raise_for_status()

        raw = response.json().get("response", "{}")
        return json.loads(raw)

    except httpx.HTTPError as e:
        print(f"[Local Model Error] {e}")
        return {
            "routing": "FALLBACK_TO_CLOUD",
            "reason": f"Local model unreachable: {e}",
            "steps": []
        }
    except json.JSONDecodeError:
        print("[Local Model Error] Non-JSON response from model.")
        return {
            "routing": "FALLBACK_TO_CLOUD",
            "reason": "Malformed local model output.",
            "steps": []
        }