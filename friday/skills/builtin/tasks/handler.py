"""Tasks skill — today's plan + scheduled jobs."""

from __future__ import annotations

import re

from friday.skills.base import Skill, SkillContext, SkillManifest, SkillResult

# Meta: build/organise the day — never store the utterance as an agenda item.
# Do not match "what's on schedule today" (listing) — that is _LIST_TODAY.
_PLAN_DAY = re.compile(
    r"\b((help (me )?)?(plan|organise|organize|map out)\s+(my |the |a )?(day|today|agenda)"
    r"|(help (me )?)?schedule\s+(my |the |a )(day|today|agenda)"
    r"|make (me )?(a )?(day )?plan|organize my day|plan my day)\b",
    re.IGNORECASE,
)
# Add a concrete item — requires add-like language (bare "plan" alone is NOT enough).
_ADD_TODAY = re.compile(
    r"\b((add|put|set)\b.{0,60}\b(to )?(my )?(plan|agenda|list|today)\b|"
    r"we('?ll| will) be doing\b|"
    r"for today\s*[:\-]|today\s*[:\-]\s+\S|"
    r"remind me today|"
    r"lock(ed)? in for today)\b",
    re.IGNORECASE,
)
_LIST_TODAY = re.compile(
    r"\b("
    r"what('?s| is) (on |up for |up with )?(my )?(plan|agenda|today|schedule)|"
    r"what\s+do\s+(we|i|you)\s+have\b.{0,40}\b(schedule|agenda|plan|today)|"
    r"what('?s| is) up( for today| today)?|"
    r"(tell me |read (me )?|give me )?(the |my |today'?s )?(plan|agenda|schedule)( for today)?|"
    r"show (me )?(my |the |today'?s )?(plan|agenda|schedule)|"
    r"today'?s (plan|agenda|tasks|schedule)|list (my )?(plan|agenda|schedule)|"
    r"what('?s| is) the plan( for today)?|"
    r"plan for today|agenda for today|schedule for today|"
    r"on (the |my )?schedule( today)?"
    r")\b",
    re.IGNORECASE,
)
_DONE = re.compile(r"\b(done|finished|completed|check off)\b", re.IGNORECASE)


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

        # Agenda briefings first — never turn a business dump into one giant reminder title.
        if RM.is_agenda_briefing(msg) and not pending:
            from friday.humor import maybe_append_quip
            from friday.tasks.day_plan import extract_agenda_items
            from friday.tasks.plan import add_item, format_for_prompt, get_plan

            items = extract_agenda_items(msg)
            added = []
            for raw in items:
                added.append(add_item(raw))
            when = RM.parse_when(msg)
            ping = None
            if when is not None and added:
                # Optional short daily/time ping — never the whole monologue as title.
                from friday.tasks.scheduler import get_scheduler

                title = "Morning check-in on today's ventures"
                sch = get_scheduler()
                sch.dedupe_cron_titles(title)
                job = sch.add_job(
                    prompt=title,
                    skill_id="reminder",
                    run_at=when.run_at,
                    cron=when.cron,
                    title=title[:80],
                    unique=True,
                )
                ping = {"job": job, "when": when.label, "title": title}
                ctx.emit("reminder_set", {"title": title, "when": when.label, "job_id": job["id"]})

            if added:
                lines = "\n".join(f"• {it['text']}" for it in added)
                from friday.persona import owner_name

                reply = (
                    f"Locked onto today's agenda, {owner_name()}:\n{lines}\n\n"
                    + (f"Also set a short ping ({ping['when']}).\n\n" if ping else "")
                    + f"Full agenda:\n{format_for_prompt()}"
                )
                if ctx.voice_mode:
                    reply = (
                        "Locked in: " + "; ".join(it["text"] for it in added) + "."
                        + (f" Ping set for {ping['when']}." if ping else "")
                    )
                reply = maybe_append_quip(reply, user_text=msg, context="agenda_add")
                return SkillResult(
                    reply=reply,
                    skill_id="tasks",
                    metadata={"added": added, "plan": get_plan(), "reminder": (ping or {}).get("job")},
                )

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
                from friday.persona import owner_name

                reply = (
                    "Still waiting on a time — for example, in 20 minutes or tomorrow at 9."
                    if asked_already
                    else f"Sure, {owner_name()}. When should I remind you? Say something like \"in 20 minutes\", \"tomorrow at 9\" or \"every weekday at 8\"."
                )
                return SkillResult(reply=reply, skill_id="tasks")
        if re.search(r"\b(reminders?|alarms?|scheduled)\b", msg, re.IGNORECASE) and re.search(r"\b(what|which|show|list|any)\b", msg, re.IGNORECASE):
            import datetime as _dt

            from friday.persona import owner_name
            from friday.tasks.scheduler import get_scheduler

            jobs = [j for j in get_scheduler().list_jobs() if j["status"] == "scheduled" and (j.get("cron") or j.get("run_at"))]
            if not jobs:
                return SkillResult(reply=f"Nothing scheduled right now, {owner_name()}.", skill_id="tasks")
            lines = []
            for j in sorted(jobs, key=lambda j: j.get("run_at") or 1e18)[:8]:
                when = j["cron"] and f"repeats ({j['cron']})" or _dt.datetime.fromtimestamp(j["run_at"]).strftime("%a %H:%M")
                lines.append(f"• {j['title']} — {when}")
            return SkillResult(reply="Here's what's coming up:\n" + "\n".join(lines), skill_id="tasks")

        from friday.humor import maybe_append_quip
        from friday.persona import owner_name
        from friday.tasks.day_plan import (
            ASKED_FOR_TASKS,
            compose_day_plan_reply,
            compose_task_capture_reply,
            extract_proposed_from_assistant,
            is_empty_task_capture,
            is_meta_plan_request,
            is_schedule_list_request,
            parse_lock_in_confirmation,
            split_task_dictation,
        )

        # Follow-up after we proposed / asked for today's list.
        last_assistant = ""
        pending_tasks = False
        for turn in reversed(ctx.history or []):
            if turn.get("role") == "assistant":
                last_assistant = turn.get("content") or ""
                pending_tasks = bool(ASKED_FOR_TASKS.search(last_assistant))
                break
        if pending_tasks:
            from friday.tasks.plan import add_item, format_for_prompt, get_plan

            # Confirmations lock the prior proposal — never treat "yes"/"lock these in" as a task title.
            if parse_lock_in_confirmation(msg):
                items = extract_proposed_from_assistant(last_assistant)
            else:
                items = split_task_dictation(msg)
            if not items:
                return SkillResult(
                    reply=(
                        f"Still waiting on the list, {owner_name()}. "
                        "Confirm to lock my proposal, or dictate the tasks."
                    ),
                    skill_id="tasks",
                    metadata={"awaiting_tasks": True},
                )
            added = [add_item(raw) for raw in items]
            if ctx.voice_mode:
                reply = "Locked in: " + "; ".join(it["text"] for it in added) + "."
            else:
                lines = "\n".join(f"• {it['text']}" for it in added)
                reply = (
                    f"Got it, {owner_name()} — locked in for today:\n{lines}\n\n"
                    f"Full agenda:\n{format_for_prompt()}"
                )
            reply = maybe_append_quip(reply, user_text=msg, context="agenda_add")
            return SkillResult(
                reply=reply,
                skill_id="tasks",
                metadata={"added": added, "plan": get_plan()},
            )

        # "Note down my tasks" — use calendar/agenda/diary/profile + model; never invent from thin air.
        if is_empty_task_capture(msg):
            built = compose_task_capture_reply(user_text=msg, voice_mode=bool(ctx.voice_mode))
            reply = maybe_append_quip(built["reply"], user_text=msg, context="agenda_add")
            return SkillResult(
                reply=reply,
                skill_id="tasks",
                metadata={
                    "awaiting_tasks": True,
                    "proposed": built.get("proposed") or [],
                    "used_senses": built.get("used_senses"),
                    "plan": built.get("plan"),
                },
            )

        # Fast path: today's agenda / "what's on schedule" — never route to plan-my-day theater.
        if (_LIST_TODAY.search(msg) or is_schedule_list_request(msg)) and not _ADD_TODAY.search(msg):
            return self._reply_today_plan(ctx, msg, maybe_append_quip)

        # "Plan my day" / organise today — propose an outline; never save the request as a task.
        if (_PLAN_DAY.search(msg) or is_meta_plan_request(msg)) and not is_schedule_list_request(msg):
            built = compose_day_plan_reply(user_text=msg, voice_mode=bool(ctx.voice_mode))
            reply = maybe_append_quip(built["reply"], user_text=msg, context="day_plan")
            return SkillResult(reply=reply, skill_id="tasks", metadata={k: v for k, v in built.items() if k != "reply"})

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
                built = compose_day_plan_reply(user_text=msg, voice_mode=bool(ctx.voice_mode))
                reply = maybe_append_quip(built["reply"], user_text=msg, context="day_plan")
                return SkillResult(
                    reply=reply,
                    skill_id="tasks",
                    metadata={k: v for k, v in built.items() if k != "reply"},
                )
            from friday.persona import owner_name

            item = add_item(text)
            data = get_plan()
            reply = (
                f"Got it, {owner_name()} — locked in for today:\n• {item['text']}\n\n"
                f"Full agenda:\n{format_for_prompt()}"
            )
            reply = maybe_append_quip(reply, user_text=msg, context="agenda_add")
            return SkillResult(reply=reply, skill_id="tasks", metadata={"added": item, "plan": data})

        if _DONE.search(msg):
            from friday.tools.registry import call_tool

            result = call_tool("plan_done", {"text": msg})
            return SkillResult(reply=result, skill_id="tasks")

        # Last resort for agenda: always answer from the local plan — never a hollow "try once more".
        if re.search(r"(?i)\b(today|plan|agenda|tasks?|to-?dos?)\b", msg):
            return self._reply_today_plan(ctx, msg, maybe_append_quip)

        from friday.prompts import OVERLAY_TASKS
        from friday.tools.react import run_react

        reply, meta = run_react(
            ctx.message,
            allowed_tools=self.manifest.tools,
            system_overlay=OVERLAY_TASKS,
            history=ctx.history,
            emit=ctx.emit,
        )
        # Replace useless ReAct failure with a real agenda read.
        if not (reply or "").strip() or re.search(
            r"(?i)couldn'?t finish that cleanly|try once more", reply or ""
        ):
            return self._reply_today_plan(ctx, msg, maybe_append_quip)
        return SkillResult(reply=reply, skill_id="tasks", metadata=meta)

    def _reply_today_plan(self, ctx: SkillContext, msg: str, maybe_append_quip) -> SkillResult:
        from friday.persona import owner_name
        from friday.tasks.day_plan import scrub_meta_items
        from friday.tasks.plan import format_for_prompt, get_plan

        scrub_meta_items()
        data = get_plan()
        open_items = [it for it in (data.get("items") or []) if not it.get("done")]
        if not open_items:
            reply = (
                f"Board's clear for today, {owner_name()}. "
                "Say what to lock in and I'll put it on the agenda."
            )
        elif ctx.voice_mode:
            tops = "; ".join((it.get("text") or "")[:60] for it in open_items[:4])
            more = f" — plus {len(open_items) - 4} more" if len(open_items) > 4 else ""
            reply = f"On today's agenda: {tops}{more}."
        else:
            reply = f"Today's plan ({data.get('date')}):\n{format_for_prompt()}"
        reply = maybe_append_quip(reply, user_text=msg, context="agenda_list")
        return SkillResult(reply=reply, skill_id="tasks", metadata={"plan": data})
