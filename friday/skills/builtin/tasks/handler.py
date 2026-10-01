"""Tasks skill — today's plan + scheduled jobs."""

from __future__ import annotations

import re

from friday.skills.base import Skill, SkillContext, SkillManifest, SkillResult

_ADD_TODAY = re.compile(
    r"\b(today|agenda|plan|we'll be doing|we will be doing|for today|"
    r"add (this )?to (my )?(plan|agenda|list)|remind me today)\b",
    re.I,
)
_LIST_TODAY = re.compile(
    r"\b(what('?s| is) (on )?(my )?(plan|agenda|today)|show (my )?plan|"
    r"today'?s (plan|agenda|tasks)|list (my )?(plan|agenda))\b",
    re.I,
)
_DONE = re.compile(r"\b(done|finished|completed|check off)\b", re.I)


class SkillHandler(Skill):
    manifest = SkillManifest(
        id="tasks",
        name="Tasks",
        description="Today's plan and scheduled jobs",
        tools=[
            "plan_add", "plan_list", "plan_done", "plan_remove",
            "schedule_task", "list_tasks", "cancel_task",
        ],
    )

    def run(self, ctx: SkillContext) -> SkillResult:
        msg = ctx.message.strip()

        # Fast path: today's agenda without a full ReAct loop.
        if _LIST_TODAY.search(msg) and not _ADD_TODAY.search(msg):
            from friday.tasks.plan import format_for_prompt, get_plan

            data = get_plan()
            reply = f"Today's plan ({data.get('date')}):\n{format_for_prompt()}"
            return SkillResult(reply=reply, skill_id="tasks", metadata={"plan": data})

        if _ADD_TODAY.search(msg):
            from friday.tasks.plan import add_item, format_for_prompt, get_plan

            # Strip framing phrases to get the actual item text.
            text = msg
            for pat in (
                r"(?i)^(hey\s+)?friday[,:]?\s*",
                r"(?i)\b(add|put|set)\b.{0,40}\b(today|plan|agenda)\b[:\-]?\s*",
                r"(?i)\bwe('?ll| will) be doing\b\s*",
                r"(?i)\bfor today\b[:\-]?\s*",
                r"(?i)\btoday\b[:\-]?\s*",
            ):
                text = re.sub(pat, "", text).strip(" .,-")
            if not text or len(text) < 3:
                text = msg
            item = add_item(text)
            data = get_plan()
            reply = (
                f"Got it, boss — locked in for today:\n• {item['text']}\n\n"
                f"Full agenda:\n{format_for_prompt()}"
            )
            return SkillResult(reply=reply, skill_id="tasks", metadata={"added": item, "plan": data})

        if _DONE.search(msg):
            from friday.tools.registry import call_tool

            result = call_tool("plan_done", {"text": msg})
            return SkillResult(reply=result, skill_id="tasks")

        from friday.tools.react import run_react

        reply, meta = run_react(
            ctx.message,
            allowed_tools=self.manifest.tools,
            system_overlay=(
                "You manage Friday's local agenda. "
                "For 'today / agenda / we'll be doing X' use plan_add / plan_list / plan_done. "
                "For timed reminders use schedule_task."
            ),
            history=ctx.history,
            emit=ctx.emit,
        )
        return SkillResult(reply=reply, skill_id="tasks", metadata=meta)
