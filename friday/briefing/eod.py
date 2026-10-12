"""End-of-day shutdown — open loops, tomorrow anchor, gentle win review."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from friday.briefing._builtin_job import settings_io, sync_job
from friday.config import DATA_DIR, ensure_data_dirs

BUILTIN_JOB_ID = "builtin:eod_shutdown"
DEFAULT_CRON = "0 18 * * *"  # 18:00 local
_SETTINGS_DEFAULTS = {"enabled": False, "cron": DEFAULT_CRON, "speak": False}


def _settings_path() -> Path:
    ensure_data_dirs()
    return Path(DATA_DIR) / "eod_settings.json"


_load_settings, _save_settings = settings_io(_settings_path, _SETTINGS_DEFAULTS)


def is_enabled() -> bool:
    env = os.getenv("FRIDAY_EOD_SHUTDOWN", "").strip().lower()
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
        "speak": bool(data.get("speak", False)),
        "job_id": BUILTIN_JOB_ID,
        "agent_schedulable": False,
    }


def _open_loops() -> list[dict[str, Any]]:
    loops: list[dict[str, Any]] = []
    try:
        from friday.tasks.plan import get_plan

        for it in get_plan().get("items") or []:
            if not it.get("done") and (it.get("text") or "").strip():
                loops.append({"kind": "plan", "text": it["text"], "id": it.get("id")})
    except Exception:  # noqa: BLE001
        pass
    try:
        from friday.assistant.inbox import list_items

        for row in list_items(limit=20, status="open"):
            loops.append({"kind": "inbox", "text": row.get("text", ""), "id": row.get("id")})
    except Exception:  # noqa: BLE001
        pass
    try:
        from friday.focus.session import parking_lot_list

        for p in parking_lot_list():
            loops.append({"kind": "parking_lot", "text": p.get("text", ""), "id": p.get("id")})
    except Exception:  # noqa: BLE001
        pass
    return loops[:30]


def _wins_today() -> list[str]:
    wins: list[str] = []
    try:
        from friday.tasks.plan import get_plan

        for it in get_plan().get("items") or []:
            if it.get("done") and (it.get("text") or "").strip():
                wins.append(it["text"])
    except Exception:  # noqa: BLE001
        pass
    return wins[:8]


def _tomorrow_first_task() -> dict[str, Any]:
    """Best-effort anchor for tomorrow — plan carry + calendar, all optional."""
    anchor: dict[str, Any] = {"text": None, "source": None, "confirmed": False}
    try:
        from friday.tasks.plan import get_plan

        undone = [
            it for it in (get_plan().get("items") or []) if not it.get("done") and (it.get("text") or "").strip()
        ]
        if undone:
            anchor["text"] = undone[0]["text"]
            anchor["source"] = "plan"
            return anchor
    except Exception:  # noqa: BLE001
        pass
    try:
        from friday.calendar.load import calendar_load

        cal = calendar_load(force_fetch=False, horizon_days=2)
        if cal.get("available"):
            for ev in cal.get("next_events") or []:
                start_iso = ev.get("start_iso")
                if not start_iso:
                    continue
                start = datetime.fromisoformat(start_iso)
                if start.date() > datetime.now().date():
                    anchor["text"] = f"First calendar item: {ev.get('title')} ({ev.get('when')})"
                    anchor["source"] = "calendar"
                    return anchor
    except Exception:  # noqa: BLE001
        pass
    anchor["text"] = "Nothing pinned yet — you can set one when you're ready."
    anchor["source"] = "placeholder"
    return anchor


def compose_eod_script(payload: dict[str, Any] | None = None) -> str:
    from friday.persona import owner_name

    payload = payload or build_eod_payload()
    boss = owner_name().title()
    parts = [f"Winding down, {boss}."]
    loops = payload.get("open_loops") or []
    if loops:
        bits = [f"{l.get('text')}" for l in loops[:5] if l.get("text")]
        parts.append(
            "Open loops you might want to note or park: " + "; ".join(bits) + ". No pressure to finish tonight."
        )
    else:
        parts.append("I don't see obvious open loops — a clean stop if you want one.")

    anchor = payload.get("tomorrow_first") or {}
    if anchor.get("text"):
        parts.append(f"For tomorrow, a possible first anchor: {anchor['text']} — adjust anytime.")

    wins = payload.get("wins") or []
    if wins:
        parts.append("Wins worth a nod: " + "; ".join(wins[:4]) + ".")
    else:
        parts.append("If anything felt like progress today, it counts — even small steps.")

    parts.append("Shutdown when you're ready; I'll stay out of the way until you call.")
    return " ".join(parts)


def build_eod_payload(*, tomorrow_text: str | None = None) -> dict[str, Any]:
    anchor = _tomorrow_first_task()
    if tomorrow_text and tomorrow_text.strip():
        anchor = {"text": tomorrow_text.strip(), "source": "owner", "confirmed": True}
    return {
        "open_loops": _open_loops(),
        "tomorrow_first": anchor,
        "wins": _wins_today(),
        "captured_at": time.time(),
    }


def confirm_tomorrow_first(text: str) -> dict[str, Any]:
    ensure_data_dirs()
    path = Path(DATA_DIR) / "eod_tomorrow_anchor.json"
    data = {"text": text.strip(), "set_at": time.time(), "for_date": (datetime.now() + timedelta(days=1)).date().isoformat()}
    from friday.atomic import write_text_atomic

    write_text_atomic(path, json.dumps(data, indent=2))
    return data


def run_eod_shutdown(*, speak: bool | None = None) -> dict[str, Any]:
    payload = build_eod_payload()
    script = compose_eod_script(payload)
    settings = _load_settings()
    do_speak = settings.get("speak", False) if speak is None else speak

    from friday.tasks.reminders import add_notification

    add_notification("End-of-day shutdown", script[:1400], job_id=BUILTIN_JOB_ID, kind="briefing")

    spoken = False
    if do_speak:
        try:
            from friday.ui.events import emit

            emit("briefing_speak", text=script[:2000])
            spoken = True
        except Exception as exc:  # noqa: BLE001
            print(f"[EOD] speak event skipped: {exc}")

    return {"script": script, "payload": payload, "spoken": spoken}


def sync_builtin_job() -> None:
    data = _load_settings()
    sync_job(
        job_id=BUILTIN_JOB_ID,
        enabled=is_enabled(),
        cron=(data.get("cron") or DEFAULT_CRON).strip(),
        title="End-of-day shutdown",
        prompt="builtin eod shutdown",
        skill_id="eod_shutdown",
    )
