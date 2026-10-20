"""Default conversational skill — Friday persona (docs/PERSONA.md)."""

from __future__ import annotations

import re

from friday.config import CHAT_NUM_CTX, CHAT_NUM_PREDICT
from friday.persona import system_prompt
from friday.skills.base import Skill, SkillContext, SkillManifest, SkillResult

_GLITCH_RE = re.compile(
    r"(?i)\b(i glitched on that|say it once more|blanked on that)\b"
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


def _honest_fallback(message: str, owner: str) -> str:
    """Last resort when the model still dumps — answer the ask, never 'I glitched'."""
    m = (message or "").strip()
    low = m.lower()
    if re.search(r"(?i)\b(too dumb|bad reply|useless|glitch)\b", low):
        return (
            f"Fair call, {owner}. That last answer failed. "
            "Say the task once more and I'll take it cleanly."
        )
    if re.search(r"(?i)\b(pull(ed)? up|research|search|look(ed)? up|findings?|ideas?)\b", low):
        return (
            f"I don't have that research on this turn, {owner}. "
            "Ask me to look it up again and I'll run search for real."
        )
    if re.search(r"(?i)\b(remember|memory|what do you (know|have))\b", low):
        return (
            f"I need a memory search for that, {owner}. "
            "Ask what I remember about a topic and I'll check notes."
        )
    short = re.sub(r"\s+", " ", m)[:80]
    if short:
        return (
            f"I didn't get a clean answer out on that, {owner}. "
            f"For \"{short}\"{'…' if len(m) > 80 else ''} — one more detail and I'll answer straight."
        )
    return f"Say that again with one more detail, {owner}, and I'll answer straight."


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
            CHAT_CHANNEL_ADDON,
            CHAT_ONGOING,
            chat_hard_retry_system,
            chat_memory_hits_block,
            chat_owner_facts_block,
        )

        kind = "voice" if ctx.voice_mode else "chat"
        system = system_prompt(kind)
        system += f"\nNow: {datetime.now().strftime('%A %d %B %Y, %I:%M %p')}."
        system += chat_owner_facts_block(owner_facts(10))
        system += chat_memory_hits_block(list(ctx.memory_hits or []))
        system += "\n\n" + CHAT_CHANNEL_ADDON
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
        from friday.assistant.reply_guard import looks_like_prompt_dump

        who = owner_name()
        if not reply:
            reply = _honest_fallback(ctx.message, who)
        elif looks_like_prompt_dump(reply):
            # Model recited scaffolding — one hard retry with clean prompt, no history ballast.
            hard = [
                {"role": "system", "content": chat_hard_retry_system(who)},
                {"role": "user", "content": ctx.message},
            ]
            retry = query_model_text(
                "",
                messages=hard,
                format_json=False,
                reasoning_mode=False,
                num_predict=160 if ctx.voice_mode else min(220, CHAT_NUM_PREDICT),
                num_ctx=2048,
                on_token=None,
                model=model_tag,
            )
            retry_text = (retry.get("message") or retry.get("raw") or "").strip()
            if retry_text and not looks_like_prompt_dump(retry_text):
                reply = retry_text
            else:
                reply = _honest_fallback(ctx.message, who)
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
