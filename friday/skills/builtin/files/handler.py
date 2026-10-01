"""Files skill — sandboxed workspace I/O."""

from __future__ import annotations

from friday.skills.base import Skill, SkillContext, SkillManifest, SkillResult


class SkillHandler(Skill):
    manifest = SkillManifest(
        id="files",
        name="Files",
        description="Workspace files",
        tools=["read_file", "write_file", "list_files"],
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
        return SkillResult(reply=reply, skill_id="files", metadata=meta)
