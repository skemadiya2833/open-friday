"""Research skill — web search + optional tool loop."""

from __future__ import annotations

from friday.skills.base import Skill, SkillContext, SkillManifest, SkillResult


class SkillHandler(Skill):
    manifest = SkillManifest(
        id="research",
        name="Research",
        description="Web research",
        tools=["web_search", "memory_search"],
    )

    def run(self, ctx: SkillContext) -> SkillResult:
        from friday.tools.react import run_react

        reply, meta = run_react(
            ctx.message,
            allowed_tools=self.manifest.tools or ["web_search", "memory_search"],
            system_overlay=self.manifest.system_overlay,
            history=ctx.history,
            emit=ctx.emit,
        )
        return SkillResult(reply=reply, skill_id="research", metadata=meta)
