from config import LOCAL_MODEL_NAME
from engine.local_model import query_local_model
from engine.cloud_model import query_cloud_model
from engine.coordinates import prepare_steps_for_execution

# Models known to be language-only (no vision). Friday will warn and skip local
# if one of these is configured, since coordinate-based screen control requires
# an actual vision-language model.
_NON_VISION_MODELS = {
    "gemma", "gemma2", "gemma3", "gemma4",
    "llama3", "llama3.1", "llama3.2", "llama3.3",
    "mistral", "mixtral",
    "phi3", "phi4",
    "qwen", "qwen2", "qwen2.5",
    "deepseek", "deepseek-r1",
    "codellama",
    "falcon",
}

# Supported actions the model is allowed to emit. Injected into the prompt so
# the model knows the full vocabulary and does not invent actions.
_ACTION_VOCABULARY = """
WIN_SEARCH   — press the Windows key, type a query, press Enter to open an app
CLICK        — left-click at pixel coordinate {"x": int, "y": int}
HOVER        — move mouse to coordinate {"x": int, "y": int}
TYPE         — type a string into the focused input {"text": str}
PASTE        — paste text via clipboard {"text": str}
PRESS_KEY    — press a single key {"key": "enter"|"tab"|"escape"|"backspace"|...}
SCROLL       — scroll at position {"direction": "up"|"down", "x": int, "y": int}
SEARCH       — open in-app Ctrl+F search {"text": str}
DRAG         — drag from one coordinate to another {"x","y","x2","y2": int}
WAIT         — pause execution {"duration": float (seconds)}
SCREENSHOT   — capture a fresh screenshot before the next step
SAVE_FILE    — save the current file via Ctrl+S
DELETE       — select all and delete (always requires operator approval)
COMPLETE     — signal the task is fully and successfully done
""".strip()

# This system prompt is the most important performance lever for local models.
def _build_system_prompt(
    native_size: tuple[int, int],
    image_size: tuple[int, int],
) -> str:
    native_w, native_h = native_size
    image_w, image_h = image_size
    return f"""
You are Friday, a desktop automation agent running on Windows 11.
You receive a screenshot of the current screen and a task to complete.
You must return a valid JSON object with exactly this shape:

{{
  "message": "One sentence describing what you are about to do.",
  "steps": [
    {{
      "action": "ACTION_NAME",
      "description": "What this step does.",
      "risky": false,
      ... action-specific fields ...
    }}
  ]
}}

SCREEN CONTEXT:
- Physical monitor: {native_w}x{native_h} pixels.
- Screenshot image you are viewing: {image_w}x{image_h} pixels.
- ALL x and y coordinates must be integers in screenshot image space (0 to {image_w - 1}, 0 to {image_h - 1}).
- Put x and y as top-level integer fields on each step, e.g. "x": 540, "y": 320.

STRICT RULES:
1. Return ONLY the JSON object. No markdown, no prose, no code fences.
2. Every step must have "action", "description", and "risky".
3. Use ONLY the following actions:

{_ACTION_VOCABULARY}

WINDOWS-SPECIFIC RULES:
4. To open an application (Notepad, Chrome, Explorer, etc.) ALWAYS use WIN_SEARCH with a "text" field.
   Example: {{"action": "WIN_SEARCH", "text": "notepad", "description": "Open Notepad via Windows search.", "risky": false}}
   NEVER try to click the taskbar, Start button, or search bar by coordinates. Use WIN_SEARCH.
5. After WIN_SEARCH, always add a WAIT step with duration 2.0 before interacting with the opened app.
6. In Notepad, TYPE directly into the editor after it opens. Do NOT click File > New.
7. To save a file use SAVE_FILE, then TYPE the filename (e.g. "hello.py") in the save dialog.
8. End every completed task with a COMPLETE step only when the task is truly finished.
9. If the screenshot shows the task is already done, emit only a COMPLETE step.
10. If you are uncertain what to do next, emit a SCREENSHOT step to get a fresh view.
11. Every CLICK, HOVER, SCROLL, and DRAG step MUST include integer "x" and "y" fields.
""".strip()


def _is_non_vision_model(model_name: str) -> bool:
    name_lower = model_name.lower()
    return any(name_lower.startswith(m) for m in _NON_VISION_MODELS)


def get_action_plan(
    objective: str,
    base64_image: str,
    native_size: tuple[int, int],
    image_size: tuple[int, int],
) -> dict:
    """
    Tries local VLM first.
    Automatically skips local and goes to cloud if a non-vision model is configured.
    Falls back to cloud if local returns no steps or signals FALLBACK_TO_CLOUD.
    """
    system_prompt = _build_system_prompt(native_size, image_size)
    skip_local = _is_non_vision_model(LOCAL_MODEL_NAME)

    if skip_local:
        print(
            f"[Router] WARNING: '{LOCAL_MODEL_NAME}' is a language model, not a VLM. "
            f"It cannot see the screen. Routing directly to cloud."
        )
        result = None
    else:
        print("[Router] Querying local model...")
        result = query_local_model(
            objective,
            base64_image,
            system_prompt=system_prompt,
            native_size=native_size,
            image_size=image_size,
        )
        routing = result.get("routing", "LOCAL")

        if routing != "FALLBACK_TO_CLOUD" and result.get("steps"):
            return _finalize_plan(result, native_size, image_size)

        print(
            f"[Router] Falling back to cloud. "
            f"Reason: {result.get('reason', 'No steps returned.')}"
        )

    print("[Router] Querying cloud model...")
    result = query_cloud_model(
        objective,
        base64_image,
        system_prompt=system_prompt,
        native_size=native_size,
        image_size=image_size,
    )
    return _finalize_plan(result, native_size, image_size)


def _finalize_plan(
    plan: dict,
    native_size: tuple[int, int],
    image_size: tuple[int, int],
) -> dict:
    steps = plan.get("steps") or []
    plan["steps"] = prepare_steps_for_execution(steps, image_size, native_size)
    return plan