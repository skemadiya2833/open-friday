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

        overlay = (self.manifest.system_overlay or "").strip() + (
            "\nThe owner is asking what you actually remember. "
            "Call memory_search with a precise query first. "
            "Then FINAL: with what you found in plain speech — or clearly say nothing was stored. "
            "Never invent quarterly reports, files, or auditor threads. "
            f"Never output a tool instruction as the spoken answer, {owner_name()}."
        )
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
