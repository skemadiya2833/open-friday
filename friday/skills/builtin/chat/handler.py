"""Default conversational skill — Friday persona (docs/PERSONA.md)."""

from __future__ import annotations

import re

from friday.config import CHAT_NUM_CTX, CHAT_NUM_PREDICT
from friday.persona import system_prompt
from friday.skills.base import Skill, SkillContext, SkillManifest, SkillResult

_GLITCH_RE = re.compile(
    r"(?i)\b("
    r"i glitched on that|say it once more|blanked on that|"
    r"give me a second and say it again|"
    r"that turn came back empty|"
    r"i'?m with you,\s+\w+\.\s+what do you need"
    r")\b"
)


def _is_poison_assistant_turn(text: str) -> bool:
    """Prior dump/glitch replies must not re-enter the model context."""
    t = (text or "").strip()
    if not t:
        return True
    if _GLITCH_RE.search(t):
        return True
    from friday.assistant.reply_guard import looks_like_prompt_dump

    return looks_like_prompt_dump(t)


def _history_messages(history: list[dict], *, limit: int = 16) -> list[dict]:
    """Clean chat history as proper roles — never a labeled transcript wrapper."""
    out: list[dict] = []
    for turn in (history or [])[-limit:]:
        role = "assistant" if turn.get("role") == "assistant" else "user"
        content = (turn.get("content") or "").strip()
        if not content:
            continue
        if role == "assistant" and _is_poison_assistant_turn(content):
            continue
        out.append({"role": role, "content": content[:900]})
    return out


def _voice_pick_answer(owner: str) -> str:
    """Practical local TTS picks — never claim an MCU/Disney clone."""
    try:
        from friday.presence.registry import active_skin

        current = active_skin().tts_voice
    except Exception:  # noqa: BLE001
        current = "af_bella"
    return (
        f"No official MCU character voice is available to use, {owner} — don't chase clones. "
        f"For a calm local Friday-like aide here, use Kokoro af_bella (Friday default), "
        f"or af_sarah / af_nicole. You're on {current} now. "
        f"Say switch voice to af_bella if you want that one."
    )


def _direct_answer(message: str, owner: str) -> str:
    """Answer from facts when the model dumps — never ask them to resend."""
    m = (message or "").strip()
    low = m.lower()
    try:
        from friday.presence.identity import identity_answer, is_identity_ask

        if is_identity_ask(m):
            return identity_answer(m, owner)
    except Exception:  # noqa: BLE001
        pass
    try:
        from friday.assistant.intent import is_voice_pick_ask

        if is_voice_pick_ask(m):
            return _voice_pick_answer(owner)
    except Exception:  # noqa: BLE001
        pass
    if re.search(r"(?i)\b(too dumb|bad reply|useless|glitch|smart enough|blanked)\b", low):
        return f"Fair, {owner}. Still here — give me the next concrete ask and I'll act."
    try:
        from friday.assistant.intent import (
            is_camera_look_utterance,
            is_memory_utterance,
            is_screen_look_utterance,
            is_tasks_utterance,
        )

        if is_screen_look_utterance(m):
            return f"Screen look belongs on the capture path, {owner}. Ask what's on my screen."
        if is_camera_look_utterance(m):
            return f"Camera look belongs on the capture path, {owner}. Ask look at me."
        if is_memory_utterance(m):
            return f"I'll check notes when that route runs, {owner}."
        if is_tasks_utterance(m):
            return f"Agenda and reminders go through the tasks path, {owner}."
    except Exception:  # noqa: BLE001
        pass
    if re.search(r"(?i)\b(?:web\s?cams?|cameras?)\b", low):
        return (
            f"Webcam is local Systems gear, {owner}. "
            "When it's on, ask look at me and I'll take a real frame."
        )
    if re.search(
        r"(?i)\b(schedule|agenda|plan for today|on today|what.+today)\b",
        low,
    ):
        return (
            f"Today's agenda lives on the local plan board, {owner}. "
            "Ask what's on schedule today, or tell me what to add."
        )
    if re.search(r"(?i)\b(pull(ed)? up|research|search|look(ed)? up|findings?)\b", low):
        return (
            f"I don't have that research locked in this turn, {owner}. "
            "Name the topic and I'll search for real."
        )
    if re.search(r"(?i)\b(remember|memory|what do you (know|have))\b", low):
        return f"Name the topic, {owner}, and I'll check notes for real."
    if re.search(
        r"(?i)\b(freecad|\.fcstd|fcstd|\bcad\b|cube|bracket|plate)\b|"
        r"\b3\s*-?\s*d\s*(model|part|file)\b|"
        r"\b(on (your|the) desktop)\b",
        low,
    ):
        return (
            f"I haven't run FreeCAD this turn, {owner}. "
            "Name the part (for example: make a 40×30×10 plate in FreeCAD) and I'll use CAD."
        )
    if re.search(r"(?i)\bwhat am i doing\b", low):
        return f"That needs a webcam frame, {owner}. Ask look at me."
    if re.search(
        r"(?i)\bwhat are you doing\b|"
        r"\bwhat('?s| is) up\b|"
        r"\bhow are you\b|"
        r"\byou (there|around|awake)\b|"
        r"^\s*(hey|hi|hello|yo)(,?\s+friday)?[!?.]*\s*$",
        low,
    ):
        return f"Right here, {owner}."
    # Never "say it again" / never empty brush-off theater.
    return f"Still here, {owner}. What's the next concrete step?"


class SkillHandler(Skill):
    manifest = SkillManifest(
        id="chat",
        name="Chat",
        description="General conversation",
        system_overlay="",  # resolved at runtime via system_prompt()
    )

    def run(self, ctx: SkillContext) -> SkillResult:
        from datetime import datetime

        from friday.agent.behavior import deep_mode_enabled, run_deep_chat
        from friday.assistant.automemory import owner_facts
        from friday.humor import maybe_append_quip
        from friday.models.local import query_model_text
        from friday.persona import owner_name
        from friday.prompts import (
            CHAT_ONGOING,
            chat_channel_addon,
            chat_hard_retry_system,
            chat_memory_hits_block,
            chat_owner_facts_block,
        )

        # Never burn chat tokens on a clear tool ask — run the skill directly.
        try:
            from friday.assistant.intent import (
                match_tool_fastpath,
                _resolve_observe_answer_retry,
                is_voice_pick_ask,
            )
            from friday.presence.modelswitch import looks_like_model_talk
            from friday.skills.registry import get_registry

            if is_voice_pick_ask(ctx.message):
                from friday.persona import owner_name

                reply = _voice_pick_answer(owner_name())
                return SkillResult(
                    reply=reply, skill_id="chat", metadata={"voice_pick": True}
                )

            fast = match_tool_fastpath(ctx.message) or _resolve_observe_answer_retry(
                ctx.message, list(ctx.history or [])
            )
            if fast is None and looks_like_model_talk(ctx.message):
                from friday.assistant.intent import Intent as _Intent

                fast = _Intent(
                    mode="talk",
                    skill_id="presence",
                    confidence=0.95,
                    objective=ctx.message,
                    reason="chat-reroute: model talk",
                    source="policy",
                )
            if fast is not None and fast.skill_id != "chat":
                target = get_registry().get(fast.skill_id)
                if target is not None:
                    labels = {
                        "observe": "Looking at your screen…",
                        "camera": "Looking through the camera…",
                        "memory": "Checking memory…",
                        "tasks": "Checking schedule…",
                        "research": "Researching…",
                        "cad": "Opening CAD…",
                        "files": "Working with files…",
                        "computer_use": "Working on the desktop…",
                    }
                    # Skills that key off the objective (look retries) need that text.
                    if (fast.objective or "").strip() and fast.objective.strip() != (
                        ctx.message or ""
                    ).strip():
                        ctx.message = fast.objective
                    ctx.emit(
                        "activity",
                        {
                            "step": "reroute",
                            "message": labels.get(
                                fast.skill_id, f"Running {fast.skill_id}…"
                            ),
                        },
                    )
                    return target.run(ctx)
        except Exception as exc:  # noqa: BLE001
            print(f"[Chat] tool fastpath reroute skipped: {exc}")

        kind = "voice" if ctx.voice_mode else "chat"
        system = system_prompt(kind)
        system += f"\nNow: {datetime.now().strftime('%A %d %B %Y, %I:%M %p')}."
        system += chat_owner_facts_block(owner_facts(10))
        system += chat_memory_hits_block(list(ctx.memory_hits or []))
        system += "\n\n" + chat_channel_addon()
        # Opt-in camera presence: one glance + appearance notes (discarded after turn).
        try:
            from friday.presence.camera_presence import presence_context_block

            cam_block = presence_context_block()
            if cam_block:
                system += "\n\n" + cam_block
                ctx.emit(
                    "activity",
                    {"step": "camera_presence", "message": "Presence glance…"},
                )
        except Exception:  # noqa: BLE001
            pass
        # Doctrine is already agent-only in system_prompt — do not re-inject here.
        hist = _history_messages(list(ctx.history or []))
        if hist:
            system += "\n" + CHAT_ONGOING

        # Proper multi-turn roles only. Never wrap history as "Recent conversation: Boss:/You:"
        # — that format taught the model to emit User:/Context:/Persona dumps.
        msgs: list[dict] = [{"role": "system", "content": system}]
        msgs.extend(hist)
        msgs.append({"role": "user", "content": ctx.message})

        def _tok(t: str) -> None:
            ctx.emit("skill_token", {"text": t})

        from friday.models.complexity import resolve_routed_chat_model

        model_tag, route_meta = resolve_routed_chat_model(ctx.message)
        use_deep = deep_mode_enabled(ctx.message) and not ctx.voice_mode
        ctx.emit("status", {"status": "thinking"})

        def _think(t: str) -> None:
            # HUD / live captions only — never TTS the raw chain-of-thought.
            snippet = (t or "").strip()
            if not snippet:
                return
            ctx.emit("thinking_token", {"token": snippet[:240]})

        if use_deep:
            result = run_deep_chat(msgs, on_token=_tok)
        else:
            result = query_model_text(
                "",
                messages=msgs,
                format_json=False,
                reasoning_mode=False,
                num_predict=160 if ctx.voice_mode else CHAT_NUM_PREDICT,
                num_ctx=CHAT_NUM_CTX,
                on_token=_tok,
                on_thinking=_think,
                model=model_tag,
            )
        if result.get("routing") == "FALLBACK_TO_CLOUD":
            why = str(result.get("reason") or "unknown error")
            print(f"[Chat] model call failed: {why}")
            reply = (
                f"My local model isn't answering right now, {owner_name()}. "
                "I tried to start Ollama; give it a few seconds and say that again."
                if "unreachable" in why.lower()
                else f"I hit a snag generating that reply ({why[:80]}). Try once more."
            )
            return SkillResult(reply=reply, skill_id="chat", metadata={"error": why})
        reply = (result.get("message") or result.get("raw") or "").strip()
        upgrades: list[str] = []
        from friday.assistant.reply_guard import (
            claims_unbacked_pc_action,
            looks_like_prompt_dump,
        )

        who = owner_name()
        if (
            not reply
            or looks_like_prompt_dump(reply)
            or claims_unbacked_pc_action(reply)
        ):
            if claims_unbacked_pc_action(reply or ""):
                print("[Chat] blocked unbacked PC/CAD claim — retrying clean")
            elif looks_like_prompt_dump(reply or ""):
                print("[Chat] blocked prompt dump — retrying clean")
            # Hard retry(s): prefer a real model answer over canned "one more detail".
            recovered = ""
            for attempt in range(2):
                hard = [
                    {"role": "system", "content": chat_hard_retry_system(who)},
                    {"role": "user", "content": ctx.message},
                ]
                retry = query_model_text(
                    "",
                    messages=hard,
                    format_json=False,
                    reasoning_mode=False,
                    num_predict=160
                    if ctx.voice_mode
                    else min(280, CHAT_NUM_PREDICT + 40),
                    num_ctx=2048,
                    on_token=_tok if attempt == 1 else None,
                    model=model_tag,
                )
                retry_text = (retry.get("message") or retry.get("raw") or "").strip()
                if (
                    retry_text
                    and not looks_like_prompt_dump(retry_text)
                    and not claims_unbacked_pc_action(retry_text)
                ):
                    recovered = retry_text
                    break
            reply = recovered or _direct_answer(ctx.message, who)
        else:
            reply, upgrades = _capture_upgrades(reply)
            reply = maybe_append_quip(
                reply,
                user_text=ctx.message,
                is_error=False,
                is_security=False,
            )
        meta = dict(route_meta)
        if isinstance(result.get("metadata"), dict):
            meta.update(result["metadata"])
        if upgrades:
            meta["upgrades_captured"] = upgrades
        return SkillResult(reply=reply, skill_id="chat", metadata=meta)


def _capture_upgrades(reply: str) -> tuple[str, list[str]]:
    """Pull UPGRADE: lines into owner profile; strip them from the spoken/chat reply."""
    captured: list[str] = []
    lines_out: list[str] = []
    for line in reply.splitlines():
        m = re.match(r"^\s*UPGRADE:\s*(.+?)\s*$", line, flags=re.IGNORECASE)
        if m:
            idea = m.group(1).strip()
            if idea:
                captured.append(idea)
            continue
        lines_out.append(line)
    if not captured:
        return reply, []
    try:
        from friday.runtime.owner_profile import add_upgrade

        for idea in captured:
            add_upgrade(idea, source="model")
    except Exception:  # noqa: BLE001
        pass
    cleaned = "\n".join(lines_out).strip()
    return cleaned or reply, captured
