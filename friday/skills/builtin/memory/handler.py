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
        from friday.tools.react import run_react

        reply, meta = run_react(
            ctx.message,
            allowed_tools=self.manifest.tools,
            system_overlay=self.manifest.system_overlay,
            history=ctx.history,
            emit=ctx.emit,
        )
        return SkillResult(reply=reply, skill_id="memory", metadata=meta)
