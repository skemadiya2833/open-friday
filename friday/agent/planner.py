"""Vision-first decision: observe screen → decide exactly ONE next action."""

from __future__ import annotations

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
        "The attached image is the CURRENT frame — your ONLY source of truth."
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

MANDATORY CYCLE (every tick):
1. OBSERVE — Describe what is ACTUALLY visible now (apps, tabs, dialogs, loaders, errors, focused field).
2. VERIFY LAST ACTION — Previous action was: {last_action}
   Did it succeed, fail, or is the UI still updating? Cite visible evidence.
3. COMPARE — What remains for the user objective?
4. DECIDE — Exactly ONE next action. Never chain. The system re-observes after you act.
5. If the last action's effect is not yet visible → WAIT (do not repeat the same click/type).

OUTPUT FORMAT (STRICT — invalid output wastes a tick):
1. Write 2–5 sentences of reasoning FIRST (observe → verify last action → decide).
2. On its own line write exactly: {ACTION_DELIMITER}
3. Then output ONLY valid JSON (no markdown fences, no prose after it):

{{
  "observation": "What is visible right now that matters.",
  "last_action_result": "success|failed|pending|unknown — one short clause of evidence",
  "message": "Why this single next action.",
  "completion_evidence": null,
  "needs_knowledge": false,
  "knowledge_query": null,
  "steps": [{{"action": "CLICK", "description": "target label", "x": 100, "y": 200, "risky": false}}]
}}

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
1. Reasoning BEFORE {ACTION_DELIMITER}; JSON AFTER. Exactly ONE step in "steps".
2. Act ONLY on UI visible in the attached frame. Never invent off-screen targets.
3. Do NOT repeat a successful recent action. If stuck, WAIT, dismiss a popup, or change strategy.
4. WIN_SEARCH opens apps — never re-launch an app that is already open/focused.
5. TYPE text must be the FULL literal string — never placeholders like "[lyrics]" or "insert content".
6. COMPLETE only when the objective is visibly achieved. Set "completion_evidence" to the on-screen proof.
7. needs_knowledge=true ONLY with action KNOWLEDGE_SEARCH and a precise knowledge_query. Never override a valid click/type with a search flag.
8. NEVER act on tools that are not part of the task: Friday's own dark control panel, a code editor / IDE (Cursor, VS Code — dark window with file tabs, line numbers, a file tree), terminals, Task Manager, Ollama, or GPU monitors. These are NOT your workspace. Never click, type, or save into them.
9. FOCUS BEFORE TYPING: Before TYPE / PASTE / SAVE_FILE / hotkeys, confirm the INTENDED app is the frontmost window and the correct field has focus (visible caret / highlighted input). If a code editor or the wrong window is in front, click the correct app (taskbar icon or its window) or re-open it first. If you are unsure which window is focused, do NOT type — click the target app first.
10. SELF-CORRECT MISTAKES: If your last action hit the wrong window or produced wrong/partial text (evidence on screen), fix it immediately BEFORE continuing: UNDO (Ctrl+Z), BACKSPACE, or SELECT_ALL then DELETE, and/or click the correct window. Never leave incorrect content in place and never repeat the same failing action.
11. REAL CONTENT ONLY: If the objective needs text you do not already know verbatim (song lyrics, articles, quotes, long facts), do NOT type it from memory. Use KNOWLEDGE_SEARCH with a precise query — it opens the results in a browser for you. Then on following ticks: click a result, SELECT the real text (or SELECT_ALL), COPY it, switch back to the target app (HOTKEY ["alt","tab"] or click its taskbar icon), and PASTE. Typing a title or a guess instead of the real content is a failure.
12. NO-PROGRESS GUARD: If the screen looks unchanged after your last action, do NOT repeat it — change target, WAIT for it to settle, or use a keyboard route.
13. Prefer WAIT over blind retries when loaders/spinners are visible.
14. KEYBOARD FIRST: Prefer reliable keyboard routes over pixel clicks whenever both work: WIN_SEARCH to open apps, NAVIGATE (Ctrl+L) for URLs, SAVE_FILE with a full path, HOTKEY ["alt","tab"] to switch windows, Ctrl+A/Ctrl+C to grab page text. Clicks are for targets with no keyboard route.
15. Use ONLY these actions:

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
        reasoning_mode=True,
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
        reasoning_mode=True,
    )


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

    if action == "TYPE" and not (step.text or "").strip():
        print("[Planner] Rejected TYPE: empty text.")
        return None

    if action == "WIN_SEARCH" and not (step.text or step.query or "").strip():
        print("[Planner] Rejected WIN_SEARCH: empty query.")
        return None

    if action == "NAVIGATE" and not (step.url or step.text or "").strip():
        print("[Planner] Rejected NAVIGATE: empty url.")
        return None

    if action == "HOTKEY" and not step.keys:
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
        prepared = prepare_action_for_execution(
            steps[0], vision.image_size, vision.native_size,
        )
        step = _validate_step(prepared, plan)

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
