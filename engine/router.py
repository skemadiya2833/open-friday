from config import CLOUD_PROVIDER, LOCAL_MODEL_NAME
from engine.local_model import query_local_model
from engine.cloud_model import query_cloud_model
from engine.coordinates import prepare_steps_for_execution
from engine.response_parser import ACTION_DELIMITER
from engine.session import TaskSession

_NON_VISION_MODELS = {
    "gemma", "gemma2", "gemma3", "gemma4",
    "llama3", "llama3.1", "llama3.2", "llama3.3",
    "mistral", "mixtral",
    "phi3", "phi4",
    "qwen2.5", "qwen2", "qwen",
    "deepseek", "deepseek-r1",
    "codellama",
    "falcon",
}

# Vision-capable models that would otherwise match a non-vision prefix (e.g. qwen3).
_VISION_MODEL_PREFIXES = (
    "llava", "minicpm-v", "bakllava", "moondream", "qwen3", "qwen3.5",
    "qwen2-vl", "qwen-vl", "gemma3-v", "llama3.2-vision", "granite3.2-vision",
)

_ACTION_VOCABULARY = """
WIN_SEARCH    — press Win key, type query, press Enter to open an app {"text": str}
CLICK         — left-click at pixel coordinate {"x": int, "y": int}
DOUBLE_CLICK  — double left-click {"x": int, "y": int}
RIGHT_CLICK   — right-click (context menu) {"x": int, "y": int}
MIDDLE_CLICK  — scroll-wheel button click {"x": int, "y": int}
MOUSE_DOWN    — press and hold a mouse button {"x": int, "y": int, "button": "left"|"right"|"middle"}
MOUSE_UP      — release a held mouse button {"x": int, "y": int, "button": "left"|"right"|"middle"}
MOUSE_MOVE    — move the cursor without clicking {"x": int, "y": int}
HOVER         — move cursor to coordinate and pause (triggers tooltips) {"x": int, "y": int}
DRAG          — pyautogui drag from point to point {"x": int, "y": int, "x2": int, "y2": int}
DRAG_DROP     — reliable mouseDown->moveTo->mouseUp for stubborn targets {"x": int, "y": int, "x2": int, "y2": int}
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
1. Return ONLY raw JSON. No markdown fences, no preamble.
2. Phases are strategic milestones — NOT low-level click sequences.
3. Do NOT include coordinates, x/y values, or specific action names.
4. Order phases logically. Typical flow: handle dialogs -> open app -> do work -> save/finish.
5. ALWAYS include an explicit phase for handling unexpected dialogs or popups BEFORE
   the main work phase. Chrome profile pickers, update prompts, permission dialogs,
   and UAC prompts are common on Windows 11 and must be anticipated.
6. Keep 3-7 phases. Each must be fully achievable before the next begins.

CONTENT TASKS (lyrics, poems, articles, long text):
- If the objective requires reproducing specific text (song lyrics, poems, etc.),
  include an early phase to OBTAIN that content unless you are certain you know
  it verbatim from memory.
- Preferred flow when unsure: open Chrome -> search for the content -> copy ->
  paste into the target app (e.g. Notepad).
- Never plan to type placeholder text like "insert lyrics here".
- Separate phases for: research content (if needed) -> open target app ->
  write/paste content -> save file.
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
    current_goal  = (current or {}).get("goal", "")

    return f"""
You are Friday, a desktop automation agent on Windows 11.
You receive a screenshot and must decide the SINGLE NEXT action only.

OUTPUT FORMAT (CRITICAL — follow exactly):
1. Write 2-5 sentences of plain-English reasoning FIRST. Describe what windows
   and apps you see in the screenshot, which phase you are on, and why your
   next action makes sense. Example:
   "I see Cursor IDE is open on the desktop. Notepad is not visible yet.
   My task is to write song lyrics in Notepad, so I should open Notepad via
   Windows search."
2. On its own line write exactly: {ACTION_DELIMITER}
3. Then the JSON object (no markdown fences):

{{
  "message": "Brief summary of the action.",
  "steps": [
    {{
      "action": "WIN_SEARCH",
      "description": "Open Notepad via Windows search.",
      "text": "notepad",
      "risky": false
    }}
  ],
  "phase_complete": false
}}

Replace the example step with the ONE action you need right now. Every step
object MUST include all required fields for that action (WIN_SEARCH requires
"text"; CLICK requires "x" and "y"; TYPE requires "text").

The "steps" array MUST contain exactly ONE action. You will receive a fresh
screenshot after every action before deciding again.

SCREEN STATE AWARENESS (CRITICAL):
- Study the screenshot BEFORE acting. Identify every open window and which app
  has focus.
- If the target app (Notepad, Chrome, etc.) is ALREADY visible on screen,
  interact with it directly (CLICK to focus, TYPE, HOTKEY, etc.).
- NEVER use WIN_SEARCH to open an app that is already open — that spawns a
  duplicate window and wastes steps.
- Check action history: if WIN_SEARCH for an app already succeeded, that app
  is open; click inside it or type into it.

CONTENT / LYRICS TASKS:
- If the task requires song lyrics or long text you cannot type accurately from
  memory, open Chrome via WIN_SEARCH, search for the lyrics, copy them, then
  paste into Notepad. Do not use placeholder text.
- If you know the lyrics accurately, TYPE them directly into Notepad.

SCREEN CONTEXT:
- Physical monitor: {native_w}x{native_h} pixels.
- Screenshot image sent to you: {image_w}x{image_h} pixels.
- ALL x and y values MUST be integers within screenshot space:
    x: 0 to {image_w - 1}
    y: 0 to {image_h - 1}
- Do NOT emit coordinates outside these ranges. If you cannot see the target
  element in the current screenshot, use WAIT or a non-destructive action until
  the UI is visible — never guess coordinates.

HIGH-LEVEL PLAN:
{session.format_phases()}

CURRENT PHASE: {current_title}
Phase goal: {current_goal}

ACTIONS ALREADY EXECUTED (do NOT repeat these):
{session.format_history()}

DIALOG AND POPUP HANDLING (CRITICAL):
- If the screenshot shows ANY unexpected dialog, popup, profile picker, update
  prompt, permission request, or UAC prompt that is NOT part of the normal
  task flow — handle it FIRST before doing anything else.
- Chrome profile picker: click the profile you want, or click "Continue without
  an account". Do not attempt to interact with the browser until the picker is dismissed.
- Windows security dialogs: click "Yes" or "Allow" unless risky.
- "Open with" dialogs: choose the correct application and click OK.
- Any dialog with a close button (X): click it if the dialog is not required.
- Set "phase_complete": false and emit only the dialog-dismissal action.
  Do not proceed with the main task until the screen is clear.

STRICT RULES:
1. Reasoning prose comes BEFORE {ACTION_DELIMITER}; JSON comes AFTER it.
2. Emit exactly ONE step in "steps" for the CURRENT phase only.
3. Only plan actions for UI elements you can see in the current screenshot.
   Never guess coordinates for elements not visible on screen.
4. Do NOT repeat work already listed in the action history.
5. WIN_SEARCH launches applications only — set "text" to the app name (e.g.
   "notepad", "chrome"). Never search for filenames; use WIN_SEARCH only to
   open apps, not to find existing files. Never WIN_SEARCH an app already open.
6. After WIN_SEARCH or any action that opens a window, the next screenshot will
   show the new state — wait for that before clicking inside the new window.
7. Set "phase_complete": true ONLY when the current phase goal is fully achieved.
8. Use COMPLETE only when the entire user task is finished.
9. Every CLICK/DOUBLE_CLICK/RIGHT_CLICK/HOVER/SCROLL/DRAG step MUST include
   integer "x" and "y" in screenshot image space.
10. TYPE "text" must be literal content — never placeholders.
11. Use ONLY the actions listed below:

{_ACTION_VOCABULARY}
""".strip()


def _is_non_vision_model(model_name: str) -> bool:
    name_lower = model_name.lower()
    if any(name_lower.startswith(p) for p in _VISION_MODEL_PREFIXES):
        return False
    return any(name_lower.startswith(m) for m in _NON_VISION_MODELS)


def _cloud_api_configured() -> bool:
    from engine.cloud_model import cloud_api_configured
    return cloud_api_configured()


def _query_with_fallback(
    objective: str,
    system_prompt: str,
    *,
    base64_image: str | None = None,
    native_size: tuple[int, int] | None = None,
    image_size: tuple[int, int] | None = None,
    require_steps: bool = True,
    step_key: str = "steps",
    reasoning_mode: bool = False,
) -> dict:
    skip_local = _is_non_vision_model(LOCAL_MODEL_NAME)

    if skip_local:
        print(
            f"[Router] '{LOCAL_MODEL_NAME}' is text-only. Routing directly to cloud."
        )
        if not _cloud_api_configured():
            print(
                f"[Router] Cloud fallback is not configured. "
                f"Set a valid API key in .env for {CLOUD_PROVIDER}, "
                f"or use a vision-capable local model."
            )
            return {"steps": [], "message": "No vision model and no cloud API key."}
        result = None
    else:
        print("[Router] Querying local model...")
        result = query_local_model(
            objective,
            base64_image,
            system_prompt=system_prompt,
            native_size=native_size,
            image_size=image_size,
            reasoning_mode=reasoning_mode,
        )
        routing  = result.get("routing", "LOCAL")
        has_content = bool(result.get(step_key)) if require_steps else True

        if routing != "FALLBACK_TO_CLOUD" and has_content:
            return result

        reason = result.get("reason", "No usable response.")
        if not _cloud_api_configured():
            print(
                f"[Router] Local model failed ({reason}) and cloud fallback is not "
                f"configured. Set a valid API key in .env for {CLOUD_PROVIDER}."
            )
            return result

        print(f"[Router] Falling back to cloud. Reason: {reason}")

    print("[Router] Querying cloud model...")
    return query_cloud_model(
        objective,
        base64_image,
        system_prompt=system_prompt,
        native_size=native_size,
        image_size=image_size,
        reasoning_mode=reasoning_mode,
    )


def create_high_level_plan(objective: str) -> dict:
    """
    Create a strategic multi-phase plan once at task start.
    No screenshot is needed for this call.
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
        phases = [
            {"title": "Handle unexpected dialogs", "goal": "Dismiss any profile pickers, popups, or permission prompts blocking the screen"},
            {"title": "Obtain content if needed", "goal": "If the task requires specific text (lyrics, etc.) not known from memory, search and copy it via Chrome"},
            {"title": "Open required application", "goal": "Launch the app needed for the task and reach its main interface"},
            {"title": "Execute task", "goal": "Perform the main work described in the objective"},
            {"title": "Save and finish", "goal": "Persist any changes and signal COMPLETE"},
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
    Given the current screenshot and session state, return exactly one next step.
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
        reasoning_mode=True,
    )
    return _finalize_plan(result, native_size, image_size)


def _finalize_plan(
    plan: dict,
    native_size: tuple[int, int],
    image_size: tuple[int, int],
) -> dict:
    steps = plan.get("steps") or []
    if len(steps) > 1:
        steps = steps[:1]
    plan["steps"] = prepare_steps_for_execution(steps, image_size, native_size)
    return plan