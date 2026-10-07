"""Vision-first decision: observe screen → decide exactly ONE next action."""

from __future__ import annotations

import re
from pathlib import Path

from friday.actions.catalog import ALL_ACTION_NAMES, COORD_ACTIONS, vocabulary_for_prompt
from friday.actions.coordinates import prepare_action_for_execution, uses_grid_coords
from friday.agent.session import AgentSession
from friday.config import (
    MAX_KNOWLEDGE_SEARCHES,
    MODEL_NAME,
    REQUIRE_COMPLETION_EVIDENCE,
)
from friday.models.cloud import cloud_api_configured, query_cloud_model
from friday.models.local import query_model_vision
from friday.models.parser import ACTION_DELIMITER
from friday.types import ActionStep, Decision, VisionPayload


def _vision_note(vision: VisionPayload) -> str:
    if vision.focused and vision.crop_origin is not None:
        ox, oy = vision.crop_origin
        cw, ch = vision.crop_native_size or vision.image_size
        return (
            f"You are viewing a ZOOMED CROP of the desktop (FOCUS mode). "
            f"Crop origin native=({ox},{oy}), crop size={cw}x{ch}px. "
            f"Coordinates are relative to THIS crop image only "
            f"(x in [0, {vision.image_size[0]-1}], y in [0, {vision.image_size[1]-1}]). "
            "Click/type relative to what you see in the crop. Use CLEAR_FOCUS for full desktop."
        )
    if vision.is_video:
        return (
            "You are watching a LIVE VIDEO STREAM of the desktop "
            f"(~{vision.frame_count} frames). Decide ONLY from what you see now."
        )
    if vision.frame_count > 1:
        return (
            f"You are watching a LIVE stream — {vision.frame_count} recent frames "
            "(oldest→newest). Act on the LATEST frame only."
        )
    return (
        "You are watching a LIVE stream of the desktop / browser. "
        "The attached image is the CURRENT FULL frame — your ONLY source of truth."
    )


def _coordinate_rules(vision: VisionPayload) -> str:
    native_w, native_h = vision.native_size
    image_w, image_h = vision.image_size
    if uses_grid_coords():
        return """SCREEN / COORDINATES:
- x,y are INTEGERS on a 0-1000 grid over the screenshot: (0,0) = top-left corner,
  (1000,1000) = bottom-right corner. Example: screen center is x=500, y=500.
- NEVER use raw pixel values or 0-1 floats. Put x,y inside the step object.
- Pointer actions (CLICK, DOUBLE_CLICK, RIGHT_CLICK, HOVER, SCROLL, MOUSE_MOVE, DRAG*) REQUIRE x,y."""
    return f"""SCREEN / COORDINATES:
- Monitor: {native_w}x{native_h}px. Model image: {image_w}x{image_h}px.
- x,y are INTEGER pixel coordinates in IMAGE space: x in [0, {image_w - 1}], y in [0, {image_h - 1}].
- Never use normalized 0-1 floats. Put x,y inside the step object.
- Pointer actions (CLICK, DOUBLE_CLICK, RIGHT_CLICK, HOVER, SCROLL, MOUSE_MOVE, DRAG*) REQUIRE x,y."""


def build_decision_prompt(session: AgentSession, vision: VisionPayload) -> str:
    knowledge_left = max(0, MAX_KNOWLEDGE_SEARCHES - session.knowledge_searches)
    last_action = session.last_action_summary or "(none — this is the first tick)"
    desktop = str(Path.home() / "Desktop")

    return f"""
You are Friday — a production vision-driven operator on Windows.
You control mouse and keyboard like a careful human.
{_vision_note(vision)}

Reply with ONLY one JSON object. No chain-of-thought, no prose, no markdown.

{{
  "observation": "what is visible that matters",
  "last_action_result": "success|failed|pending|unknown",
  "message": "one short clause: the action you are taking",
  "completion_evidence": null,
  "needs_knowledge": false,
  "knowledge_query": null,
  "steps": [{{"action": "TYPE", "text": "full literal text to type", "description": "why"}}]
}}

Previous action: {last_action}
Decide exactly ONE next action. If the last action's effect is not visible yet → WAIT.

{_coordinate_rules(vision)}

ENVIRONMENT:
- Windows 11. Desktop folder: {desktop}
- To save a file somewhere specific, use SAVE_FILE with the FULL path,
  e.g. {{"action": "SAVE_FILE", "text": "{desktop}\\\\MyFile.txt"}} — the Save dialog accepts full paths.

USER OBJECTIVE:
{session.objective}

RUNTIME CONTEXT:
{session.format_context()}

KNOWLEDGE BUDGET: {knowledge_left} search(es) remaining (of {MAX_KNOWLEDGE_SEARCHES}).

HARD RULES:
1. JSON only. Exactly ONE step in "steps".
2. Act ONLY on UI visible in the attached frame. Never invent off-screen targets.
2b. TYPE / PASTE MUST include the FULL literal string in "text". Never leave "text" empty. If the objective is to write code, put the complete code in "text" on this tick.
3. Do NOT repeat a successful recent action. If stuck, WAIT, dismiss a popup, or change strategy.
4. WIN_SEARCH opens apps — never re-launch an app that is already open/focused.
5. TYPE text must be the FULL literal string — never placeholders like "[lyrics]" or "insert content".
6. COMPLETE only when the objective is visibly achieved. Set "completion_evidence" to the on-screen proof.
7. OBSERVE-ONLY OBJECTIVES: If the user only asked what is on screen / to describe the desktop / "can you see…", do NOT click or type. On the FIRST tick output COMPLETE with completion_evidence summarizing what you see, and put that summary in "observation" and "message".
8. needs_knowledge=true ONLY with action KNOWLEDGE_SEARCH and a precise knowledge_query. Never override a valid click/type with a search flag.
9. NEVER act on tools that are not part of the task: Friday's own dark control panel, Task Manager, Ollama, or GPU monitors — unless the user explicitly asked. Cursor and VS Code are the SAME IDE (electron editor with tabs/sidebar). If the objective mentions Cursor chat / Composer / Agent / "fix in Cursor", THAT editor IS the target — do not avoid it or hunt for a separate Cursor app.
10. FOCUS BEFORE TYPING: Before TYPE / PASTE / SAVE_FILE / hotkeys, confirm the INTENDED app is the frontmost window and the correct field has focus (visible caret / highlighted input). If a code editor or the wrong window is in front, click the correct app (taskbar icon or its window) or re-open it first. If you are unsure which window is focused, do NOT type — click the target app first.
11. SELF-CORRECT MISTAKES: If your last action hit the wrong window or produced wrong/partial text (evidence on screen), fix it immediately BEFORE continuing: UNDO (Ctrl+Z), BACKSPACE, or SELECT_ALL then DELETE, and/or click the correct window. Never leave incorrect content in place and never repeat the same failing action.
12. REAL CONTENT ONLY: If the objective needs text you do not already know verbatim (song lyrics, articles, quotes, long facts), use KNOWLEDGE_SEARCH once. It returns titles/snippets in knowledge notes. Then COMPLETE or PASTE from those notes — do not open extra tabs.
13. NO-PROGRESS GUARD: If the screen looks unchanged after your last action, do NOT repeat it — change target, WAIT for it to settle, or use a keyboard route.
14. Prefer WAIT over blind retries when loaders/spinners are visible.
15. KEYBOARD FIRST: Prefer reliable keyboard routes over pixel clicks whenever both work: WIN_SEARCH to open apps, NAVIGATE for URLs, SAVE_FILE with a full path, HOTKEY {{"keys":["alt","tab"]}} to switch windows, SELECT_ALL/COPY to grab page text. Clicks are for targets with no keyboard route.
16. PRECISION / CROP: If the target is small or you are unsure of exact pixels (chat input, icon, button), first use FOCUS with x,y near the target center (amount≈220). The next tick receives a zoomed crop — then CLICK/TYPE accurately. Use CLEAR_FOCUS to return to full desktop.
17. DO NOT click unrelated UI (Commit, Source Control, random IDE chrome) unless the objective explicitly asks for it.
18. RUN_SHELL: For Windows commands / terminal work, prefer RUN_SHELL with the full command in "text" instead of trying to click through a terminal UI. It requires approval and the UI shows what ran.
19. CURSOR / IDE CHAT: When the objective is to type into Cursor/VS Code AI chat:
    - Open chat with HOTKEY {{"keys":["ctrl","l"]}} (fallback {{"keys":["ctrl","i"]}}).
    - Command Palette: HOTKEY {{"keys":["ctrl","shift","p"]}} then TYPE a command name.
    - Do NOT click the taskbar looking for a separate "Cursor" window if the editor is already visible.
    - After the chat input is focused (caret visible), TYPE the full message, then PRESS_KEY enter if needed.
20. HOTKEY FORMAT: Always pass keys as a JSON array of lowercase names, e.g. {{"action":"HOTKEY","keys":["ctrl","shift","p"],"description":"Command Palette"}}. Never omit "keys".
21. If knowledge notes already contain search results for this objective, COMPLETE now and put those facts in "message" / "observation". Do NOT KNOWLEDGE_SEARCH, NEW_TAB, or NAVIGATE to Google again.
22. Use ONLY these actions:

{vocabulary_for_prompt()}
""".strip()


def _query_with_fallback(prompt: str, vision: VisionPayload, objective: str) -> dict:
    print(
        f"[Planner] Querying {MODEL_NAME} "
        f"({'video' if vision.is_video else f'{vision.frame_count} frame(s)'})..."
    )
    result = query_model_vision(
        prompt,
        frame_b64_list=vision.frame_b64_list or None,
        video_b64=vision.video_b64,
        reasoning_mode=False,
    )

    routing = result.get("routing", "LOCAL")
    if routing != "FALLBACK_TO_CLOUD" and result.get("steps"):
        return result

    reason = result.get("reason") or result.get("message") or "No usable response."
    print(f"[Planner] Model failed ({reason})")
    if not cloud_api_configured():
        print("[Planner] Cloud fallback is not configured.")
        return result

    print(f"[Planner] Falling back to cloud. Reason: {reason}")
    return query_cloud_model(
        objective,
        vision.frame_b64,
        system_prompt=prompt,
        reasoning_mode=False,
    )


_TYPE_KEYS = ("text", "content", "value", "input", "body", "code", "payload", "string")
_INSTRUCTION = re.compile(
    r"^(type|enter|write|paste|replace|insert|put|the python|python code)\b",
    re.I,
)


def fill_type_text(step: ActionStep, plan: dict | None = None, objective: str = "") -> ActionStep:
    """Recover the string to type from wrapped JSON, description, or the objective. Never leave TYPE empty."""
    if (step.text or "").strip():
        return step
    for key in _TYPE_KEYS:
        val = step.extras.get(key)
        if isinstance(val, str) and val.strip():
            step.text = val
            return step
    desc = (step.description or "").strip()
    if desc and not _INSTRUCTION.match(desc) and len(desc) >= 2:
        step.text = desc
        return step
    blob = "\n".join(str((plan or {}).get(k) or "") for k in ("message", "observation"))
    fenced = re.search(r"```(?:\w+)?\s*\n(.*?)```", blob, re.S)
    if fenced and fenced.group(1).strip():
        step.text = fenced.group(1).strip()
        return step
    quoted = re.search(r"""(?:type|write|enter)\s+["'](.+?)["']""", blob, re.I | re.S)
    if quoted:
        step.text = quoted.group(1)
        return step
    obj = (objective or str((plan or {}).get("_objective") or "")).strip()
    if obj:
        m = re.search(
            r"""(?:type|write|enter)\s+(?:exactly\s+)?(?:the\s+)?(?:word|text|string)?\s*:?\s*["'](.+?)["']""",
            obj,
            re.I,
        )
        if m:
            step.text = m.group(1)
            return step
        if re.search(r"\bpython\b", obj, re.I):
            step.text = 'print("hello")\n'
            print("[Planner] TYPE had no text — using a short Python payload from the objective.")
            return step
        composed = _compose_type_payload(obj)
        if composed:
            step.text = composed
            print("[Planner] TYPE had no text — composed payload from the objective.")
    return step


def _compose_type_payload(objective: str) -> str:
    try:
        from friday.models.local import query_model_text

        res = query_model_text(
            "Output ONLY the exact text to type into the app. No markdown, no explanation.\n"
            f"User asked: {objective[:500]}",
            format_json=False,
            reasoning_mode=False,
            num_predict=220,
            num_ctx=1024,
        )
        text = (res.get("message") or res.get("raw") or "").strip()
        text = re.sub(r"^```(?:\w+)?\s*|\s*```$", "", text).strip()
        return text[:4000] if text and "routing" not in res else ""
    except Exception as exc:  # noqa: BLE001
        print(f"[Planner] compose TYPE payload failed: {exc}")
        return ""


def decide_next_action(session: AgentSession, vision: VisionPayload) -> Decision:
    """Observe the current vision payload and return exactly one action decision."""
    prompt = build_decision_prompt(session, vision)
    user_tail = (
        f"\n\nStream tick: {session.iteration}\n"
        f"Previous action: {session.last_action_summary or '(none)'}\n"
        "Re-evaluate the CURRENT frame. Decide the single best next action now."
    )
    result = _query_with_fallback(prompt + user_tail, vision, session.objective)

    # Retry with a single latest frame if multi-frame/video returned nothing.
    if not result.get("steps") and vision.frame_count > 1 and vision.frame_b64_list:
        print("[Planner] Retrying with single latest frame...")
        single = VisionPayload(
            native_size=vision.native_size,
            image_size=vision.image_size,
            frame_b64_list=[vision.frame_b64_list[-1]],
            is_video=False,
            frame_count=1,
        )
        single_prompt = build_decision_prompt(session, single) + user_tail
        result = _query_with_fallback(single_prompt, single, session.objective)

    return _to_decision(result, vision, session)


def _validate_step(step: ActionStep, plan: dict) -> ActionStep | None:
    action = step.action.upper()
    if action not in ALL_ACTION_NAMES and action != "SCREENSHOT":
        print(f"[Planner] Rejected unknown action: {action}")
        return None

    if action in COORD_ACTIONS and (step.x is None or step.y is None):
        print(f"[Planner] Rejected {action}: missing coordinates.")
        return None

    if action in ("TYPE", "PASTE") and not (step.text or "").strip():
        fill_type_text(step, plan, str((plan or {}).get("_objective") or ""))
    if action in ("TYPE", "PASTE") and not (step.text or "").strip():
        print("[Planner] Rejected TYPE: empty text.")
        return None

    if action == "WIN_SEARCH" and not (step.text or step.query or "").strip():
        print("[Planner] Rejected WIN_SEARCH: empty query.")
        return None

    if action == "NAVIGATE" and not (step.url or step.text or "").strip():
        print("[Planner] Rejected NAVIGATE: empty url.")
        return None

    if action == "HOTKEY" and not step.keys:
        # Last-chance recovery from key/text/description (e.g. "Ctrl+Shift+P").
        from friday.types import coerce_keys, extract_chord

        recovered = (
            coerce_keys(step.key)
            or coerce_keys(step.text)
            or coerce_keys(step.extras.get("hotkey") if step.extras else None)
            or coerce_keys(step.extras.get("chord") if step.extras else None)
            or extract_chord(step.description)
        )
        if recovered and len(recovered) > 1:
            step.keys = recovered
            step.key = None
        elif recovered and len(recovered) == 1:
            step.action = "PRESS_KEY"
            step.key = recovered[0]
            step.keys = None
            action = "PRESS_KEY"
        else:
            print("[Planner] Rejected HOTKEY: empty keys.")
            return None

    if action == "PRESS_KEY" and not (step.key or "").strip():
        print("[Planner] Rejected PRESS_KEY: empty key.")
        return None

    if action == "COMPLETE" and REQUIRE_COMPLETION_EVIDENCE:
        evidence = str(plan.get("completion_evidence") or "").strip()
        if not evidence or evidence.lower() in ("null", "none", "n/a"):
            print("[Planner] Rejected COMPLETE: missing completion_evidence.")
            return None

    if action == "KNOWLEDGE_SEARCH" and not (step.query or step.text or "").strip():
        print("[Planner] Rejected KNOWLEDGE_SEARCH: empty query.")
        return None

    return step


def _to_decision(plan: dict, vision: VisionPayload, session: AgentSession) -> Decision:
    steps = plan.get("steps") or []
    if len(steps) > 1:
        print(f"[Planner] Model returned {len(steps)} steps; keeping only the first.")
        steps = steps[:1]

    step: ActionStep | None = None
    if steps:
        map_native = vision.crop_native_size or vision.native_size
        prepared = prepare_action_for_execution(
            steps[0],
            vision.image_size,
            map_native,
            crop_origin=vision.crop_origin,
        )
        if prepared.action.upper() in ("TYPE", "PASTE"):
            fill_type_text(prepared, plan, session.objective)
        step = _validate_step(prepared, {**plan, "_objective": session.objective})

    needs_knowledge = bool(plan.get("needs_knowledge"))
    knowledge_query = plan.get("knowledge_query")

    # Only promote to KNOWLEDGE_SEARCH when there is no competing valid action.
    if (
        step is None
        and needs_knowledge
        and knowledge_query
        and session.can_knowledge_search()
    ):
        step = ActionStep(
            action="KNOWLEDGE_SEARCH",
            query=str(knowledge_query),
            description=f"Look up: {knowledge_query}",
        )

    observation = str(plan.get("observation") or "")
    last_result = str(plan.get("last_action_result") or "").strip()
    if last_result:
        observation = f"{observation} [last: {last_result}]".strip()

    return Decision(
        message=str(plan.get("message") or ""),
        step=step,
        observation=observation,
        needs_knowledge=needs_knowledge,
        knowledge_query=str(knowledge_query) if knowledge_query else None,
        raw=plan,
    )
