"""Default conversational skill — Friday persona (docs/PERSONA.md)."""

from __future__ import annotations

from friday.config import CHAT_NUM_CTX, CHAT_NUM_PREDICT
from friday.persona import system_prompt
from friday.skills.base import Skill, SkillContext, SkillManifest, SkillResult


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

        kind = "voice" if ctx.voice_mode else "chat"
        system = system_prompt(kind)
        system += f"\nNow: {datetime.now().strftime('%A %d %B %Y, %I:%M %p')}."
        facts = owner_facts(10)
        if facts:
            system += "\n\nWhat you remember about the owner (use naturally, do not recite):\n- " + "\n- ".join(facts)
        if ctx.memory_hits:
            system += "\n\nRelevant notes:\n- " + "\n- ".join(h[:600] for h in ctx.memory_hits[:4])
        system += (
            "\n\nYou have the whole conversation above this message. "
            "Never claim you cannot remember earlier turns. "
            "You are a real assistant on this PC — prefer concrete help over empty offers. "
            "Do-or-deny: act with tools when the ask is actionable; if you cannot, say you cannot "
            "and what you need — never invent completed work, open documents, metrics, or status. "
            "Never say you cannot browse websites or only have an 'internal knowledge base' — "
            "research and file tools exist; if they did not run, ask one clarifying question instead."
        )
        try:
            from friday.runtime.doctrine import prompt_block

            doctrine = prompt_block()
            if doctrine:
                system += "\n\n" + doctrine
        except Exception:  # noqa: BLE001
            pass
        if ctx.history:
            system += "\nOngoing conversation — do not greet or introduce yourself."

        msgs: list[dict] = [{"role": "system", "content": system}]
        for turn in ctx.history[-20:]:
            role = "assistant" if turn.get("role") == "assistant" else "user"
            content = (turn.get("content") or "")[:900]
            if content:
                msgs.append({"role": role, "content": content})
        user = ctx.message
        if ctx.history:
            tail = []
            boss = owner_name().title()
            for turn in ctx.history[-6:]:
                who = boss if turn.get("role") == "user" else "You"
                bit = (turn.get("content") or "").replace("\n", " ")[:180]
                if bit:
                    tail.append(f"{who}: {bit}")
            if tail:
                user = "Recent conversation:\n" + "\n".join(tail) + f"\n\n{boss} now: " + ctx.message
        msgs.append({"role": "user", "content": user})

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
        if not reply:
            reply = f"Say that again, {owner_name()}?"
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
    import re

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
