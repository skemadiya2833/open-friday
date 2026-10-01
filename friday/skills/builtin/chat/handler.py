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
        from friday.models.local import query_model_text

        mem_block = ""
        if ctx.memory_hits:
            mem_block = "Memories:\n- " + "\n- ".join(ctx.memory_hits[:3]) + "\n\n"

        history_txt = ""
        for turn in ctx.history[-4:]:
            role = turn.get("role", "user").upper()
            content = (turn.get("content") or "")[:400]
            history_txt += f"{role}: {content}\n"

        system = PERSONA_VOICE if ctx.voice_mode else (self.manifest.system_overlay or PERSONA_CHAT)
        prompt = (
            f"{system}\n\n"
            f"{mem_block}"
            f"{history_txt}"
            f"USER: {ctx.message}\n"
            "ASSISTANT:"
        )

        def _tok(t: str) -> None:
            ctx.emit("skill_token", {"text": t})

        num_predict = 96 if ctx.voice_mode else CHAT_NUM_PREDICT
        result = query_model_text(
            prompt,
            format_json=False,
            reasoning_mode=False,
            num_predict=num_predict,
            num_ctx=min(CHAT_NUM_CTX, 2048 if ctx.voice_mode else CHAT_NUM_CTX),
            on_token=_tok,
        )
        reply = (result.get("message") or result.get("raw") or "").strip()
        if not reply:
            reply = "I'm here, boss." if ctx.voice_mode else (
                "Online and listening, boss. Chat, research, memory, or a desktop task — your call."
            )
        return SkillResult(reply=reply, skill_id="chat")
