"""Opt-in nudges — quiet hours, caps, snooze; no guilt, no escalation."""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from friday.config import DATA_DIR, ensure_data_dirs


def _path() -> Path:
    ensure_data_dirs()
    return Path(DATA_DIR) / "nudge_settings.json"


def _defaults() -> dict[str, Any]:
    return {
        "opt_in": False,
        "quiet_start": 22,  # hour 0-23 local
        "quiet_end": 7,
        "daily_cap": 3,
        "stop_suggesting": False,
        "snooze_until": 0.0,
        "sent_today": 0,
        "sent_date": "",
        "last_reason": "",
    }


def _load() -> dict[str, Any]:
    p = _path()
    base = _defaults()
    if not p.is_file():
        return base
    try:
        base.update(json.loads(p.read_text(encoding="utf-8")))
    except Exception:
        pass
    return base


def _save(data: dict[str, Any]) -> None:
    from friday.atomic import write_text_atomic

    write_text_atomic(_path(), json.dumps(data, indent=2))


def _roll_day(data: dict[str, Any]) -> None:
    today = datetime.now().strftime("%Y-%m-%d")
    if data.get("sent_date") != today:
        data["sent_date"] = today
        data["sent_today"] = 0


def status() -> dict[str, Any]:
    d = _load()
    _roll_day(d)
    return {
        "opt_in": bool(d.get("opt_in")),
        "quiet_hours": {"start": int(d.get("quiet_start", 22)), "end": int(d.get("quiet_end", 7))},
        "daily_cap": int(d.get("daily_cap", 3)),
        "sent_today": int(d.get("sent_today", 0)),
        "stop_suggesting": bool(d.get("stop_suggesting")),
        "snooze_until": float(d.get("snooze_until") or 0),
        "last_reason": d.get("last_reason") or "",
    }


def configure(
    *,
    opt_in: bool | None = None,
    quiet_start: int | None = None,
    quiet_end: int | None = None,
    daily_cap: int | None = None,
) -> dict[str, Any]:
    data = _load()
    if opt_in is not None:
        data["opt_in"] = bool(opt_in)
    if quiet_start is not None:
        data["quiet_start"] = max(0, min(23, int(quiet_start)))
    if quiet_end is not None:
        # 24 = exclusive end-of-day so 0→24 covers every hour (tests + "always quiet").
        data["quiet_end"] = max(0, min(24, int(quiet_end)))
    if daily_cap is not None:
        data["daily_cap"] = max(0, min(20, int(daily_cap)))
    _save(data)
    return status()


def stop_suggesting(reason: str = "") -> dict[str, Any]:
    data = _load()
    data["stop_suggesting"] = True
    data["last_reason"] = (reason or "owner asked to stop")[:200]
    _save(data)
    return status()


def snooze(minutes: int = 60) -> dict[str, Any]:
    data = _load()
    data["snooze_until"] = time.time() + max(5, min(int(minutes), 7 * 24 * 60)) * 60
    _save(data)
    return status()


def _in_quiet_hours(data: dict[str, Any]) -> bool:
    hour = datetime.now().hour
    start = int(data.get("quiet_start", 22))
    end = int(data.get("quiet_end", 7))
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def may_nudge(*, reason: str) -> dict[str, Any]:
    """Decide whether a nudge may fire; returns explain-why payload (does not increment)."""
    return _evaluate(reason, increment=False)


def record_nudge_sent(reason: str) -> dict[str, Any]:
    return _evaluate(reason, increment=True)


def _evaluate(reason: str, *, increment: bool) -> dict[str, Any]:
    data = _load()
    _roll_day(data)
    if not data.get("opt_in"):
        return {"allow": False, "why": "Nudges are off until you opt in."}
    if data.get("stop_suggesting"):
        return {"allow": False, "why": "You asked me to stop suggesting — honoring that."}
    if float(data.get("snooze_until") or 0) > time.time():
        return {"allow": False, "why": "Snoozed — I'll wait until the snooze window ends."}
    if _in_quiet_hours(data):
        return {"allow": False, "why": "Quiet hours — I'll stay silent for now."}
    cap = int(data.get("daily_cap", 3))
    if cap <= 0:
        return {"allow": False, "why": "Daily cap is set to zero."}
    if int(data.get("sent_today", 0)) >= cap:
        return {"allow": False, "why": "Daily nudge cap reached — no more today unless you raise the cap."}
    try:
        from friday.focus.session import quiet_mode_enabled

        if quiet_mode_enabled():
            return {"allow": False, "why": "Focus quiet mode is on — no sounds or nudges."}
    except Exception:  # noqa: BLE001
        pass
    if increment:
        data["sent_today"] = int(data.get("sent_today", 0)) + 1
        data["last_reason"] = reason[:200]
        _save(data)
    return {"allow": True, "why": reason, "message_tone": "offer_only"}
