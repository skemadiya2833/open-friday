"""Vision-first decision: observe screen → decide exactly ONE next action."""

from __future__ import annotations

import re

from friday.actions.catalog import ALL_ACTION_NAMES, COORD_ACTIONS
from friday.actions.coordinates import prepare_action_for_execution
from friday.agent.session import AgentSession
from friday.config import (
    MODEL_NAME,
    REQUIRE_COMPLETION_EVIDENCE,
)
from friday.models.cloud import cloud_api_configured, query_cloud_model
from friday.models.local import query_model_vision
from friday.prompts import build_decision_prompt
from friday.types import ActionStep, Decision, VisionPayload


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
        # Allow "type exactly: \"...\"" (no space before colon) and "type the word '...'".
        m = re.search(
            r"""(?:type|write|enter)\s+(?:exactly\s*)?(?:the\s+)?(?:word|text|string)?\s*:?\s*["'](.+?)["']""",
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
    if action == "WIN_SEARCH":
        q = (step.text or step.query or "").strip().lower()
        if re.search(r"\b(chrome|edge|firefox|browser|msedge|google chrome)\b", q):
            print("[Planner] Rejected WIN_SEARCH for browser — use NAVIGATE / RUN_SHELL instead.")
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
