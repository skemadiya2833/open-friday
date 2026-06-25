from config import LOCAL_MODEL_NAME, MAX_STEPS_PER_BATCH
from engine.local_model import query_local_model
from engine.cloud_model import query_cloud_model
from engine.coordinates import prepare_steps_for_execution
from engine.session import TaskSession

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

_ACTION_VOCABULARY = """
WIN_SEARCH    — press Win key, type a query, press Enter to open an app {"text": str}
CLICK         — left-click at pixel coordinate {"x": int, "y": int}
DOUBLE_CLICK  — double left-click {"x": int, "y": int}
RIGHT_CLICK   — right-click (context menu) {"x": int, "y": int}
MIDDLE_CLICK  — scroll-wheel button click {"x": int, "y": int}
MOUSE_DOWN    — press and hold a mouse button {"x": int, "y": int, "button": "left"|"right"|"middle"}
MOUSE_UP      — release a held mouse button {"x": int, "y": int, "button": "left"|"right"|"middle"}
MOUSE_MOVE    — move the cursor without clicking {"x": int, "y": int}
HOVER         — move cursor to coordinate and pause (triggers tooltips) {"x": int, "y": int}
DRAG          — pyautogui drag from point to point {"x": int, "y": int, "x2": int, "y2": int}
DRAG_DROP     — reliable mouseDown→moveTo→mouseUp for stubborn targets {"x": int, "y": int, "x2": int, "y2": int}
SCROLL        — scroll wheel at position {"x": int, "y": int, "direction": "up"|"down"|"left"|"right", "amount": int (default 3)}
TYPE          — type a string via clipboard paste {"text": str}
PASTE         — explicitly paste provided text via clipboard {"text": str}
PRESS_KEY     — press a single key {"key": "enter"|"tab"|"escape"|...}
HOTKEY        — press multiple keys simultaneously {"keys": ["ctrl","c"] | ...}
KEY_DOWN      — hold a key without releasing {"key": str}
KEY_UP        — release a held key {"key": str}
SELECT_ALL    — Ctrl+A to select all content in focused element
COPY          — Ctrl+C to copy selection
CUT           — Ctrl+X to cut selection
UNDO          — Ctrl+Z to undo last action
REDO          — Ctrl+Y to redo last undone action
SEARCH        — open in-app Ctrl+F find bar {"text": str}
SAVE_FILE     — Ctrl+S then optionally type filename in dialog {"text": optional_filename}
SCREENSHOT    — pause and capture a fresh screenshot before continuing
WAIT          — pause execution {"duration": float (seconds)}
DELETE        — select all and delete (RISKY — always requires approval)
COMPLETE      — signal the task is fully and successfully done
""".strip()


def _build_high_level_prompt() -> str:
    return """
You are Friday, a desktop automation agent on Windows 11.
The user has given you a task. Create a HIGH-LEVEL strategic plan only.

Return ONLY a JSON object with this shape:
{
  "message": "One sentence summarizing your overall approach.",
  "phases": [
    {
      "title": "Short phase name",
      "goal": "What must be true when this phase is complete."
    }
  ]
}

RULES:
1. Return ONLY JSON. No markdown, no code fences.
2. Phases are strategic milestones — NOT low-level click sequences.
3. Do NOT include coordinates, x/y values, or specific HOTKEY/CLICK steps.
4. Order phases logically. Typical flow for content tasks:
   open app → fetch/locate content → transfer content → save/finish.
5. If lyrics, poems, or other verbatim text must be fetched from the web,
   include explicit phases for: open browser, navigate to content, copy content,
   open destination app, paste, save.
6. Keep 3–6 phases. Each phase should be completable before moving to the next.
""".strip()


def _build_runtime_prompt(
    session: TaskSession,
    native_size: tuple[int, int],
    image_size: tuple[int, int],
) -> str:
    native_w, native_h = native_size
    image_w, image_h = image_size
    current = session.current_phase
    current_title = (current or {}).get("title", "Unknown")
    current_goal = (current or {}).get("goal", "")

    return f"""
You are Friday, a desktop automation agent on Windows 11.
You receive a screenshot and must decide the NEXT IMMEDIATE actions only.

Return ONLY a JSON object:
{{
  "message": "What you are doing right now, given the screen and history.",
  "steps": [
    {{
      "action": "ACTION_NAME",
      "description": "What this step does.",
      "risky": false,
      ... action-specific fields ...
    }}
  ],
  "phase_complete": false
}}

SCREEN CONTEXT:
- Physical monitor: {native_w}x{native_h} pixels.
- Screenshot image: {image_w}x{image_h} pixels.
- ALL x and y coordinates must be integers in screenshot space (0–{image_w - 1}, 0–{image_h - 1}).

HIGH-LEVEL PLAN (created at task start — follow it, do not restart from scratch):
{session.format_phases()}

CURRENT PHASE: {current_title}
Phase goal: {current_goal}

ACTIONS ALREADY EXECUTED (do NOT repeat these):
{session.format_history()}

STRICT RULES:
1. Return ONLY JSON. No markdown, no prose outside JSON.
2. Emit at most {MAX_STEPS_PER_BATCH} steps for the CURRENT phase only.
3. Plan only what you can do given the CURRENT screenshot. Never guess coordinates
   for UI you cannot see.
4. Do NOT re-do work listed in the action history (e.g. do not open Chrome again
   if it is already open and you already searched).
5. WIN_SEARCH "text" MUST NEVER be empty — always set an app name like "chrome" or "notepad".
6. After WIN_SEARCH, add WAIT duration 2.0 before interacting with the new window.
7. End with a SCREENSHOT step when the screen will change and you need a fresh view
   before the next batch of actions.
8. Set "phase_complete": true only when the current phase goal is fully achieved.
9. Use COMPLETE only when the entire user task is done.
10. Every CLICK/HOVER/SCROLL/DRAG step MUST include integer "x" and "y".
11. TYPE "text" must be literal content — never placeholders like "insert lyrics here".
    If you need lyrics from the web, you must be in the copy-content phase with the
    page visible; use SELECT_ALL + COPY, not TYPE with fake text.
12. Use ONLY these actions:

{_ACTION_VOCABULARY}
""".strip()


def _is_non_vision_model(model_name: str) -> bool:
    name_lower = model_name.lower()
    return any(name_lower.startswith(m) for m in _NON_VISION_MODELS)


def _query_with_fallback(
    objective: str,
    system_prompt: str,
    *,
    base64_image: str | None = None,
    native_size: tuple[int, int] | None = None,
    image_size: tuple[int, int] | None = None,
    require_steps: bool = True,
    step_key: str = "steps",
) -> dict:
    """Query local VLM first, fall back to cloud on failure."""
    skip_local = _is_non_vision_model(LOCAL_MODEL_NAME)

    if skip_local:
        print(
            f"[Router] WARNING: '{LOCAL_MODEL_NAME}' is a language model, not a VLM. "
            f"Routing directly to cloud."
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
        has_content = bool(result.get(step_key)) if require_steps else True

        if routing != "FALLBACK_TO_CLOUD" and has_content:
            return result

        print(
            f"[Router] Falling back to cloud. "
            f"Reason: {result.get('reason', 'No usable response.')}"
        )

    print("[Router] Querying cloud model...")
    return query_cloud_model(
        objective,
        base64_image,
        system_prompt=system_prompt,
        native_size=native_size,
        image_size=image_size,
    )


def create_high_level_plan(objective: str) -> dict:
    """
    Create a strategic multi-phase plan once at task start (no screenshot needed).
    """
    system_prompt = _build_high_level_prompt()
    result = _query_with_fallback(
        objective,
        system_prompt,
        require_steps=False,
        step_key="phases",
    )
    phases = result.get("phases") or []
    if not phases:
        # Sensible default so runtime always has a plan to follow
        phases = [
            {"title": "Assess and prepare", "goal": "Open required apps and reach starting state"},
            {"title": "Execute task", "goal": "Perform the main work described in the objective"},
            {"title": "Finish", "goal": "Verify result and signal COMPLETE"},
        ]
    return {
        "message": result.get("message", ""),
        "phases": phases,
    }


def get_next_steps(
    session: TaskSession,
    base64_image: str,
    native_size: tuple[int, int],
    image_size: tuple[int, int],
) -> dict:
    """
    Given the current screenshot and session memory, return the next batch of steps.
    """
    system_prompt = _build_runtime_prompt(session, native_size, image_size)
    user_context = (
        f"User objective: {session.objective}\n"
        f"Iteration: {session.iteration}\n"
        f"Remember what you already did. Continue from the current phase."
    )
    result = _query_with_fallback(
        user_context,
        system_prompt,
        base64_image=base64_image,
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
