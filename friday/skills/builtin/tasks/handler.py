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

        from friday.tasks import reminders as RM

        pending = False
        for turn in reversed(ctx.history or []):
            if turn.get("role") == "assistant":
                pending = bool(RM.ASKED_WHEN.search(turn.get("content") or ""))
                break

        # Reminders, timers and recurring jobs: schedule immediately, no approval round-trip, no JSON dump.
        if RM.is_reminder_request(msg) or pending:
            text = msg
            if pending and not RM.is_reminder_request(msg):
                prev = next((t.get("content") or "" for t in reversed(ctx.history or []) if t.get("role") == "user"), "")
                text = f"{prev} {msg}".strip()
            made = RM.schedule_from_text(text)
            if made:
                ctx.emit("reminder_set", {"title": made["title"], "when": made["when"], "job_id": made["job"]["id"]})
                return SkillResult(reply=made["reply"], skill_id="tasks", metadata={"reminder": made["job"]})
            if RM.is_reminder_request(msg) or pending:
                return SkillResult(
                    reply="Sure, boss. When should I remind you? Say something like \"in 20 minutes\", \"tomorrow at 9\" or \"every weekday at 8\".",
                    skill_id="tasks",
                )
        if re.search(r"\b(reminders?|alarms?|scheduled)\b", msg, re.I) and re.search(r"\b(what|which|show|list|any)\b", msg, re.I):
            import datetime as _dt

            from friday.tasks.scheduler import get_scheduler

            jobs = [j for j in get_scheduler().list_jobs() if j["status"] == "scheduled" and (j.get("cron") or j.get("run_at"))]
            if not jobs:
                return SkillResult(reply="Nothing scheduled right now, boss.", skill_id="tasks")
            lines = []
            for j in sorted(jobs, key=lambda j: j.get("run_at") or 1e18)[:8]:
                when = j["cron"] and f"repeats ({j['cron']})" or _dt.datetime.fromtimestamp(j["run_at"]).strftime("%a %H:%M")
                lines.append(f"• {j['title']} — {when}")
            return SkillResult(reply="Here's what's coming up:\n" + "\n".join(lines), skill_id="tasks")

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

        # Never dump tool JSON at the owner. Timed work is handled above; leftover agenda goes through tools internally.
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
