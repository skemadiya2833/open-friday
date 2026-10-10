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
        system += f"\nNow: {datetime.now().strftime('%A %d %B %Y, %H:%M')}."
        facts = owner_facts(10)
        if facts:
            system += "\n\nWhat you remember about the owner (use naturally, do not recite):\n- " + "\n- ".join(facts)
        if ctx.memory_hits:
            system += "\n\nRelevant notes:\n- " + "\n- ".join(h[:600] for h in ctx.memory_hits[:4])
        system += "\n\nYou have the whole conversation above this message. Never claim you cannot remember earlier turns."
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
        if not reply:
            reply = f"Say that again, {owner_name()}?"
        else:
            reply = maybe_append_quip(
                reply,
                user_text=ctx.message,
                is_error=False,
                is_security=False,
            )
        meta = {}
        if isinstance(result.get("metadata"), dict):
            meta.update(result["metadata"])
        return SkillResult(reply=reply, skill_id="chat", metadata=meta)
