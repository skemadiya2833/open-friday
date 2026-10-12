"""Tasks skill — today's plan + scheduled jobs."""

from __future__ import annotations

import re

from friday.skills.base import Skill, SkillContext, SkillManifest, SkillResult

# Meta: build/organise the day — never store the utterance as an agenda item.
_PLAN_DAY = re.compile(
    r"\b((help (me )?)?(plan|organise|organize|schedule|map out)\s+(my |the |a )?(day|today|agenda)"
    r"|make (me )?(a )?(day )?plan|organize my day|plan my day)\b",
    re.I,
)
# Add a concrete item — requires add-like language (bare "plan" alone is NOT enough).
_ADD_TODAY = re.compile(
    r"\b((add|put|set)\b.{0,60}\b(to )?(my )?(plan|agenda|list|today)\b|"
    r"we('?ll| will) be doing\b|"
    r"for today\s*[:\-]|today\s*[:\-]\s+\S|"
    r"remind me today|"
    r"lock(ed)? in for today)\b",
    re.I,
)
_LIST_TODAY = re.compile(
    r"\b(what('?s| is) (on )?(my )?(plan|agenda|today)|show (my )?plan|"
    r"today'?s (plan|agenda|tasks)|list (my )?(plan|agenda)|what('?s| is) the plan)\b",
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
            # Voice echo of our own "when?" prompt must not re-ask forever.
            if pending and RM.ASKED_WHEN.search(msg):
                return SkillResult(
                    reply="Still waiting on a time — for example, in 20 minutes or tomorrow at 9.",
                    skill_id="tasks",
                    metadata={"echo_suppressed": True},
                )
            text = msg
            if pending and not RM.is_reminder_request(msg):
                prev = next(
                    (t.get("content") or "" for t in reversed(ctx.history or [])
                     if t.get("role") == "user" and not RM.ASKED_WHEN.search(t.get("content") or "")),
                    "",
                )
                text = f"{prev} {msg}".strip()
            made = RM.schedule_from_text(text)
            if made:
                ctx.emit("reminder_set", {"title": made["title"], "when": made["when"], "job_id": made["job"]["id"]})
                return SkillResult(reply=made["reply"], skill_id="tasks", metadata={"reminder": made["job"]})
            if RM.is_reminder_request(msg) or pending:
                # Alternate wording so the next mic echo does not match ASKED_WHEN again.
                asked_already = any(
                    RM.ASKED_WHEN.search(t.get("content") or "")
                    for t in (ctx.history or [])[-4:]
                    if t.get("role") == "assistant"
                )
                reply = (
                    "Still waiting on a time — for example, in 20 minutes or tomorrow at 9."
                    if asked_already
                    else "Sure, boss. When should I remind you? Say something like \"in 20 minutes\", \"tomorrow at 9\" or \"every weekday at 8\"."
                )
                return SkillResult(reply=reply, skill_id="tasks")
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

        from friday.humor import maybe_append_quip
        from friday.tasks.day_plan import compose_day_plan_reply, is_meta_plan_request

        # "Plan my day" / organise today — propose an outline; never save the request as a task.
        if _PLAN_DAY.search(msg) or is_meta_plan_request(msg):
            built = compose_day_plan_reply(user_text=msg)
            reply = maybe_append_quip(built["reply"], user_text=msg, context="day_plan")
            return SkillResult(reply=reply, skill_id="tasks", metadata={k: v for k, v in built.items() if k != "reply"})

        # Fast path: today's agenda without a full ReAct loop.
        if _LIST_TODAY.search(msg) and not _ADD_TODAY.search(msg):
            from friday.tasks.day_plan import scrub_meta_items
            from friday.tasks.plan import format_for_prompt, get_plan

            scrub_meta_items()
            data = get_plan()
            reply = f"Today's plan ({data.get('date')}):\n{format_for_prompt()}"
            reply = maybe_append_quip(reply, user_text=msg, context="agenda_list")
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
            if is_meta_plan_request(text) or is_meta_plan_request(msg):
                built = compose_day_plan_reply(user_text=msg)
                reply = maybe_append_quip(built["reply"], user_text=msg, context="day_plan")
                return SkillResult(
                    reply=reply,
                    skill_id="tasks",
                    metadata={k: v for k, v in built.items() if k != "reply"},
                )
            item = add_item(text)
            data = get_plan()
            reply = (
                f"Got it, boss — locked in for today:\n• {item['text']}\n\n"
                f"Full agenda:\n{format_for_prompt()}"
            )
            reply = maybe_append_quip(reply, user_text=msg, context="agenda_add")
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
