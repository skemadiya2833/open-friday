from config import MODEL_NAME
from engine.local_model import query_model_text, query_model_vision
from engine.cloud_model import cloud_api_configured, query_cloud_model
from engine.coordinates import prepare_steps_for_execution
from engine.response_parser import ACTION_DELIMITER
from engine.session import TaskSession
from engine.stream import VisionPayload

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
    {"title": "Short phase name", "goal": "What must be true when this phase is complete."}
  ]
}

RULES:
1. Return ONLY raw JSON. No markdown fences, no preamble.
2. Phases are strategic milestones — NOT low-level click sequences.
3. Do NOT include coordinates or specific action names.
4. Order phases logically: handle dialogs -> open app -> do work -> save/finish.
5. Only add a "Handle Dialogs" phase when the task may trigger popups (installers, saves).
   Simple tasks like Notepad do not need a separate dialog phase.
6. Keep 3-6 phases.
""".strip()


def _vision_note(vision: VisionPayload) -> str:
    if vision.is_video:
        return (
            "You are watching a LIVE VIDEO STREAM of the desktop "
            f"(~{vision.frame_count} frames, recent motion). "
            "Decide the next action from what you see happening on screen."
        )
    if vision.frame_count > 1:
        return (
            f"You are watching a LIVE stream — {vision.frame_count} recent frames "
            "(oldest→newest). Decide the next action from the latest state."
        )
    return (
        "You are watching a LIVE stream of the desktop. "
        "The attached image is the current frame. Decide the next action now."
    )


def _build_runtime_prompt(
    session: TaskSession,
    vision: VisionPayload,
) -> str:
    native_w, native_h = vision.native_size
    image_w, image_h = vision.image_size
    current = session.current_phase
    current_title = (current or {}).get("title", "Unknown")
    current_goal = (current or {}).get("goal", "")

    return f"""
You are Friday, a desktop automation agent on Windows 11.
{_vision_note(vision)}

OUTPUT FORMAT (CRITICAL):
1. Write 2-5 sentences of reasoning FIRST — what you see, current phase, why this action.
2. On its own line write exactly: {ACTION_DELIMITER}
3. Then output ONLY the JSON object below — no other text, no prose, no coordinate lines:

{{
  "message": "Brief summary of the action.",
  "steps": [{{"action": "CLICK", "description": "...", "x": 100, "y": 200, "risky": false}}],
  "phase_complete": false
}}

Put x and y INSIDE the step object. CLICK steps must include integer x and y.

SCREEN CONTEXT:
- Monitor: {native_w}x{native_h}px. Model image space: {image_w}x{image_h}px.
- x/y integers in image space: x 0–{image_w - 1}, y 0–{image_h - 1}.

TASK CONTEXT:
{session.format_context()}

HIGH-LEVEL PLAN:
{session.format_phases()}

CURRENT PHASE: {current_title}
Phase goal: {current_goal}

DIALOG AND BACKGROUND APPS (CRITICAL):
- Only interact with UI for the USER'S TASK (Notepad, Chrome, save dialogs, etc.).
- IGNORE Task Manager, Ollama, llama-server, GPU monitors, and Friday's own overlay panel.
- Do NOT click inside Task Manager — it is not part of the task.

DIALOG PHASE:
- If current phase is "Handle Dialogs" and you see NO modal, popup, or permission dialog:
  set "phase_complete": true and emit {{"action": "WAIT", "duration": 0.3, "risky": false}}.
- NEVER CLICK random desktop areas to "check" for dialogs. No dialog visible = WAIT + phase_complete.
- Only CLICK when a real blocking dialog is on screen (UAC, "Open with", save picker, etc.).

TYPE / PASTE:
- TYPE text must be the FULL literal string to paste — every line of lyrics, every paragraph.
- NEVER type descriptions like "Lyrics of Back to December" or "insert lyrics here".
- For songs: include the actual verse/chorus text in the "text" field (use \\n for line breaks).

STRICT RULES:
1. Reasoning BEFORE {ACTION_DELIMITER}; JSON AFTER.
2. Exactly ONE step for the CURRENT phase.
3. Only act on UI visible in the live stream.
4. Do NOT repeat work in RECENT ACTIONS.
5. WIN_SEARCH opens apps only — never re-launch an app already open.
6. Set phase_complete true only when the phase goal is achieved.
7. CLICK steps need integer x,y in image space.
8. Use ONLY these actions:

{_ACTION_VOCABULARY}
""".strip()


def _query_with_fallback(
    prompt: str,
    vision: VisionPayload | None = None,
    *,
    require_steps: bool = True,
    step_key: str = "steps",
    reasoning_mode: bool = False,
    format_json: bool = False,
) -> dict:
    if vision and (vision.video_b64 or vision.frame_b64_list):
        mode = "video" if vision.is_video else f"{vision.frame_count} frame(s)"
    else:
        mode = "text"
    print(f"[Router] Querying {MODEL_NAME} ({mode})...")

    if vision and (vision.video_b64 or vision.frame_b64_list):
        result = query_model_vision(
            prompt,
            frame_b64_list=vision.frame_b64_list or None,
            video_b64=vision.video_b64,
            reasoning_mode=reasoning_mode,
        )
    else:
        result = query_model_text(prompt, format_json=format_json, reasoning_mode=reasoning_mode)

    routing = result.get("routing", "LOCAL")
    has_content = bool(result.get(step_key)) if require_steps else True
    if routing != "FALLBACK_TO_CLOUD" and has_content:
        return result

    reason = result.get("reason") or result.get("message") or "No usable response."
    print(f"[Router] Model failed ({reason})")
    if not cloud_api_configured():
        print("[Router] Cloud fallback is not configured.")
        return result

    print(f"[Router] Falling back to cloud. Reason: {reason}")
    fallback_image = None
    if vision and vision.frame_b64_list:
        fallback_image = vision.frame_b64_list[-1]
    return query_cloud_model(
        prompt, fallback_image, system_prompt="", reasoning_mode=reasoning_mode,
    )


def create_high_level_plan(objective: str) -> dict:
    prompt = f"{_build_high_level_prompt()}\n\nUser objective: {objective}"
    result = _query_with_fallback(
        prompt, require_steps=False, step_key="phases", format_json=True,
    )
    phases = result.get("phases") or []
    if not phases:
        phases = [
            {"title": "Handle unexpected dialogs", "goal": "Dismiss popups blocking the screen"},
            {"title": "Open required application", "goal": "Launch the app and reach its main UI"},
            {"title": "Execute task", "goal": "Perform the main work"},
            {"title": "Save and finish", "goal": "Persist changes and signal COMPLETE"},
        ]
    return {"message": result.get("message", ""), "phases": phases}


def get_next_steps(session: TaskSession, vision: VisionPayload) -> dict:
    """Observe live stream and return exactly one next action."""
    system_prompt = _build_runtime_prompt(session, vision)
    user_context = (
        f"User objective: {session.objective}\n"
        f"Stream tick: {session.iteration}\n"
        f"Continue from the current phase."
    )
    full_prompt = f"{system_prompt}\n\n{user_context}"

    result = _query_with_fallback(full_prompt, vision, reasoning_mode=True)

    # Retry with a single latest frame if multi-frame/video returned nothing.
    if not result.get("steps") and vision.frame_count > 1 and vision.frame_b64_list:
        print("[Router] Retrying with single latest frame...")
        single = VisionPayload(
            native_size=vision.native_size,
            image_size=vision.image_size,
            frame_b64_list=[vision.frame_b64_list[-1]],
            is_video=False,
            frame_count=1,
        )
        single_prompt = f"{_build_runtime_prompt(session, single)}\n\n{user_context}"
        result = _query_with_fallback(single_prompt, single, reasoning_mode=True)

    return _finalize_plan(result, vision.native_size, vision.image_size)


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
