"""Default conversational skill — MCU Friday persona."""

from __future__ import annotations

from friday.config import CHAT_NUM_CTX, CHAT_NUM_PREDICT
from friday.persona import PERSONA_CHAT, PERSONA_VOICE
from friday.skills.base import Skill, SkillContext, SkillManifest, SkillResult


class SkillHandler(Skill):
    manifest = SkillManifest(
        id="chat",
        name="Chat",
        description="General conversation",
        system_overlay=PERSONA_CHAT,
    )

    def run(self, ctx: SkillContext) -> SkillResult:
        from datetime import datetime

        from friday.assistant.automemory import owner_facts
        from friday.models.local import query_model_text

        system = PERSONA_VOICE if ctx.voice_mode else (self.manifest.system_overlay or PERSONA_CHAT)
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
            for turn in ctx.history[-6:]:
                who = "Boss" if turn.get("role") == "user" else "You"
                bit = (turn.get("content") or "").replace("\n", " ")[:180]
                if bit:
                    tail.append(f"{who}: {bit}")
            if tail:
                user = "Recent conversation:\n" + "\n".join(tail) + "\n\nBoss now: " + ctx.message
        msgs.append({"role": "user", "content": user})

        def _tok(t: str) -> None:
            ctx.emit("skill_token", {"text": t})

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
                "My local model isn't answering right now, boss. I tried to start Ollama; give it a few seconds and say that again."
                if "unreachable" in why.lower() else f"I hit a snag generating that reply ({why[:80]}). Try once more."
            )
            return SkillResult(reply=reply, skill_id="chat", metadata={"error": why})
        reply = (result.get("message") or result.get("raw") or "").strip()
        return SkillResult(reply=reply or "Say that again, boss?", skill_id="chat")
