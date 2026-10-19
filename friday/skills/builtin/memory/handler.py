"""Memory skill — RAG ingest / query via tools."""

from __future__ import annotations

from friday.skills.base import Skill, SkillContext, SkillManifest, SkillResult


class SkillHandler(Skill):
    manifest = SkillManifest(
        id="memory",
        name="Memory",
        description="Vector memory",
        tools=["memory_search", "memory_add", "memory_delete"],
    )

    def run(self, ctx: SkillContext) -> SkillResult:
        from friday.persona import owner_name
        from friday.tools.react import run_react

        from friday.prompts import overlay_memory

        overlay = (self.manifest.system_overlay or "").strip() + overlay_memory(owner_name())
        reply, meta = run_react(
            ctx.message,
            allowed_tools=self.manifest.tools,
            system_overlay=overlay,
            history=ctx.history,
            emit=ctx.emit,
        )
        if not (reply or "").strip():
            reply = f"Nothing useful in memory on that, {owner_name()}."
        return SkillResult(reply=reply, skill_id="memory", metadata=meta)
