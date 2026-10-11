# Copyright 2025 The OpenJarvis Authors
# Licensed under the Apache License, Version 2.0
# Source: open-jarvis/OpenJarvis src/openjarvis/tools/digest_collect.py
#         (sectioned digest pattern; WORLD/weather/news ideas only)
# Commit: f9e9d5d28d9e58d7fe601c331fc15a02fad32b2c
# Changes for Friday: local sources only (plan, reminders, weather/news via
# existing tools). No Gmail/Calendar OAuth connectors. Built-in scheduler job
# owner-toggled; agents cannot create morning_briefing schedules.

"""Local morning briefing — digest of plan, reminders, weather, news."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from friday.config import DATA_DIR, ensure_data_dirs

BUILTIN_JOB_ID = "builtin:morning_briefing"
DEFAULT_CRON = "0 8 * * *"  # 08:00 local daily


def _settings_path() -> Path:
    ensure_data_dirs()
    return Path(DATA_DIR) / "briefing_settings.json"


def _load_settings() -> dict[str, Any]:
    path = _settings_path()
    if not path.exists():
        return {"enabled": False, "cron": DEFAULT_CRON, "speak": True}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"enabled": False, "cron": DEFAULT_CRON, "speak": True}
    data.setdefault("enabled", False)
    data.setdefault("cron", DEFAULT_CRON)
    data.setdefault("speak", True)
    return data


def _save_settings(data: dict[str, Any]) -> None:
    from friday.atomic import write_text_atomic

    write_text_atomic(_settings_path(), json.dumps(data, indent=2))


def is_enabled() -> bool:
    env = os.getenv("FRIDAY_MORNING_BRIEFING", "").strip().lower()
    if env in ("1", "true", "yes", "on"):
        return True
    if env in ("0", "false", "no", "off"):
        return False
    return bool(_load_settings().get("enabled"))


def set_enabled(enabled: bool, *, cron: str | None = None, speak: bool | None = None) -> dict[str, Any]:
    data = _load_settings()
    data["enabled"] = bool(enabled)
    if cron:
        data["cron"] = cron.strip()
    if speak is not None:
        data["speak"] = bool(speak)
    _save_settings(data)
    sync_builtin_job()
    return status()


def status() -> dict[str, Any]:
    data = _load_settings()
    return {
        "enabled": is_enabled(),
        "cron": data.get("cron") or DEFAULT_CRON,
        "speak": bool(data.get("speak", True)),
        "job_id": BUILTIN_JOB_ID,
        "agent_schedulable": False,
    }


def collect_local_digest(*, fetch_world: bool = True) -> dict[str, Any]:
    """Gather local-only briefing sections (no OAuth connectors)."""
    sections: dict[str, Any] = {"plan": [], "reminders": [], "weather": "", "news": []}

    try:
        from friday.tasks.plan import get_plan

        plan = get_plan()
        sections["plan"] = [
            it.get("text") or ""
            for it in (plan.get("items") or [])
            if not it.get("done") and (it.get("text") or "").strip()
        ][:12]
    except Exception as exc:  # noqa: BLE001
        sections["plan_error"] = str(exc)[:120]

    try:
        from friday.tasks.scheduler import get_scheduler

        now = time.time()
        jobs = [
            j
            for j in get_scheduler().list_jobs()
            if j.get("status") == "scheduled"
            and (j.get("skill_id") or "") == "reminder"
            and j.get("id") != BUILTIN_JOB_ID
        ]
        upcoming = []
        for j in jobs:
            label = (j.get("title") or j.get("prompt") or "reminder")[:120]
            when = ""
            if j.get("run_at"):
                when = datetime.fromtimestamp(float(j["run_at"])).strftime("%H:%M")
            elif j.get("cron"):
                when = f"cron {j['cron']}"
            upcoming.append({"title": label, "when": when, "run_at": j.get("run_at")})
        upcoming.sort(key=lambda r: float(r["run_at"] or now + 86400))
        sections["reminders"] = upcoming[:8]
    except Exception as exc:  # noqa: BLE001
        sections["reminders_error"] = str(exc)[:120]

    if fetch_world:
        try:
            from friday.knowledge.search import fetch_web_results

            weather_rows = fetch_web_results("weather today", limit=2)
            if weather_rows:
                sections["weather"] = (
                    (weather_rows[0].get("title") or "")
                    + ". "
                    + (weather_rows[0].get("snippet") or "")
                ).strip()[:280]
            news_rows = fetch_web_results("today headlines", limit=4)
            sections["news"] = [
                (r.get("title") or "").strip()[:140] for r in news_rows if r.get("title")
            ][:4]
        except Exception as exc:  # noqa: BLE001
            sections["world_error"] = str(exc)[:120]

    return sections


def compose_spoken_briefing(digest: dict[str, Any] | None = None) -> str:
    """Friday-persona spoken script from local digest (no model required)."""
    from friday.persona import owner_name

    digest = digest or collect_local_digest(fetch_world=False)
    boss = owner_name().title()
    now = datetime.now()
    parts = [f"Good morning, {boss}. It's {now.strftime('%A')}, {now.strftime('%d %B')}."]

    plan = [p for p in (digest.get("plan") or []) if p]
    if plan:
        parts.append("On today's plan: " + "; ".join(plan[:5]) + ".")
    else:
        parts.append("Your plan for today is clear so far.")

    rems = digest.get("reminders") or []
    if rems:
        bits = []
        for r in rems[:4]:
            when = r.get("when") or ""
            bits.append(f"{r.get('title')}{(' at ' + when) if when else ''}")
        parts.append("Reminders coming up: " + "; ".join(bits) + ".")
    else:
        parts.append("No reminders on the board.")

    weather = (digest.get("weather") or "").strip()
    if weather:
        parts.append("Weather: " + weather)

    news = [n for n in (digest.get("news") or []) if n]
    if news:
        parts.append("Headlines: " + "; ".join(news[:3]) + ".")

    parts.append("Say the word when you want to dig into any of that.")
    return " ".join(parts)


def run_morning_briefing(*, speak: bool | None = None, fetch_world: bool = True) -> dict[str, Any]:
    """Collect, notify, optionally speak. Returns payload for tests/API."""
    digest = collect_local_digest(fetch_world=fetch_world)
    script = compose_spoken_briefing(digest)
    settings = _load_settings()
    do_speak = settings.get("speak", True) if speak is None else speak

    from friday.tasks.reminders import add_notification

    add_notification("Morning briefing", script[:1400], job_id=BUILTIN_JOB_ID, kind="briefing")

    spoken = False
    if do_speak:
        try:
            # Emit a UI event so the browser/live client can TTS the script
            # (server has no speaker device path; Edge TTS is client-driven).
            from friday.ui.events import emit

            emit("briefing_speak", text=script[:2000])
            spoken = True
        except Exception as exc:  # noqa: BLE001
            print(f"[Briefing] speak event skipped: {exc}")

    return {"script": script, "digest": digest, "spoken": spoken}


def sync_builtin_job() -> None:
    """Arm or disarm the built-in cron job. Not creatable via schedule_task."""
    from friday.tasks.scheduler import get_scheduler

    sch = get_scheduler()
    settings = _load_settings()
    cron = (settings.get("cron") or DEFAULT_CRON).strip()

    # Remove any prior arming of this id from APScheduler + DB row we own.
    try:
        sch.cancel(BUILTIN_JOB_ID)
    except Exception:  # noqa: BLE001
        pass

    if not is_enabled():
        return

    # Insert/replace built-in job with a stable id (bypass uuid in add_job).
    ts = time.time()
    with sch._lock, sch._conn() as conn:  # noqa: SLF001 — intentional built-in path
        conn.execute("DELETE FROM jobs WHERE id=?", (BUILTIN_JOB_ID,))
        conn.execute(
            "INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                BUILTIN_JOB_ID,
                "Morning briefing",
                "builtin morning briefing",
                "morning_briefing",
                "scheduled",
                cron,
                None,
                ts,
                None,
                json.dumps({"builtin": True, "agent_schedulable": False}),
            ),
        )
        conn.commit()
    job = {
        "id": BUILTIN_JOB_ID,
        "title": "Morning briefing",
        "prompt": "builtin morning briefing",
        "skill_id": "morning_briefing",
        "status": "scheduled",
        "cron": cron,
        "run_at": None,
        "created_at": ts,
        "last_run": None,
        "meta": {"builtin": True},
    }
    sch._arm(job)  # noqa: SLF001
