"""Weekly review — on-demand report + optional owner-scheduled built-in job."""

from __future__ import annotations

import os
import time
from datetime import datetime
from typing import Any

from friday.briefing._builtin_job import settings_io, sync_job
from pathlib import Path

from friday.config import DATA_DIR, ensure_data_dirs

BUILTIN_JOB_ID = "builtin:weekly_review"
DEFAULT_CRON = "0 9 * * 0"  # Sunday 09:00
_SETTINGS_DEFAULTS = {"enabled": False, "cron": DEFAULT_CRON}


def _settings_path() -> Path:
    ensure_data_dirs()
    return Path(DATA_DIR) / "weekly_review_settings.json"


_load_settings, _save_settings = settings_io(_settings_path, _SETTINGS_DEFAULTS)


def is_enabled() -> bool:
    env = os.getenv("FRIDAY_WEEKLY_REVIEW", "").strip().lower()
    if env in ("1", "true", "yes", "on"):
        return True
    if env in ("0", "false", "no", "off"):
        return False
    return bool(_load_settings().get("enabled"))


def set_enabled(enabled: bool, *, cron: str | None = None) -> dict[str, Any]:
    data = _load_settings()
    data["enabled"] = bool(enabled)
    if cron:
        data["cron"] = cron.strip()
    _save_settings(data)
    sync_builtin_job()
    return status()


def status() -> dict[str, Any]:
    data = _load_settings()
    return {
        "enabled": is_enabled(),
        "cron": data.get("cron") or DEFAULT_CRON,
        "job_id": BUILTIN_JOB_ID,
        "agent_schedulable": False,
    }


def build_weekly_report(*, days: int = 7) -> dict[str, Any]:
    since = time.time() - days * 86400
    report: dict[str, Any] = {
        "period_days": days,
        "generated_at": time.time(),
        "plan_done": [],
        "plan_open": [],
        "inbox_open": 0,
        "calendar_highlights": [],
        "reflection_prompts": [
            "What actually moved the needle this week?",
            "What should get less time next week?",
            "One commitment worth protecting on the calendar?",
        ],
    }
    try:
        from friday.tasks.plan import get_plan

        for it in get_plan().get("items") or []:
            text = (it.get("text") or "").strip()
            if not text:
                continue
            if it.get("done"):
                report["plan_done"].append(text)
            else:
                report["plan_open"].append(text)
    except Exception as exc:  # noqa: BLE001
        report["plan_error"] = str(exc)[:120]

    try:
        from friday.assistant.inbox import list_items

        report["inbox_open"] = len(list_items(limit=200, status="open"))
    except Exception:  # noqa: BLE001
        pass

    try:
        from friday.calendar.load import calendar_load

        cal = calendar_load(force_fetch=False, horizon_days=7)
        if cal.get("available"):
            report["calendar_highlights"] = (cal.get("events_today") or [])[:3]
            report["calendar_summary"] = cal.get("summary")
    except Exception as exc:  # noqa: BLE001
        report["calendar_error"] = str(exc)[:120]

    report["since"] = since
    return report


def compose_weekly_script(report: dict[str, Any] | None = None) -> str:
    from friday.persona import owner_name

    report = report or build_weekly_report()
    boss = owner_name().title()
    now = datetime.now()
    parts = [f"Weekly check-in, {boss} — {now.strftime('%d %B')}."]
    done = report.get("plan_done") or []
    if done:
        parts.append("Marked done recently on the plan: " + "; ".join(done[:6]) + ".")
    open_items = report.get("plan_open") or []
    if open_items:
        parts.append("Still open if you want to revisit: " + "; ".join(open_items[:5]) + ".")
    if report.get("calendar_summary"):
        parts.append("Calendar note: " + str(report["calendar_summary"]))
    parts.append("Take what helps; skip the rest — no scorekeeping.")
    return " ".join(parts)


def run_weekly_review() -> dict[str, Any]:
    report = build_weekly_report()
    script = compose_weekly_script(report)
    from friday.tasks.reminders import add_notification

    add_notification("Weekly review", script[:1400], job_id=BUILTIN_JOB_ID, kind="briefing")
    return {"script": script, "report": report}


def sync_builtin_job() -> None:
    data = _load_settings()
    sync_job(
        job_id=BUILTIN_JOB_ID,
        enabled=is_enabled(),
        cron=(data.get("cron") or DEFAULT_CRON).strip(),
        title="Weekly review",
        prompt="builtin weekly review",
        skill_id="weekly_review",
    )
