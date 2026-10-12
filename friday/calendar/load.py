"""Load calendar events into a briefing-friendly summary (local iCal only)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from friday.calendar.secrets import configured


def _serialize_event(ev: dict[str, Any]) -> dict[str, Any]:
    start = ev.get("start")
    end = ev.get("end")
    fmt = "%H:%M"
    if ev.get("all_day"):
        when = "all day"
    elif isinstance(start, datetime):
        when = start.strftime(fmt)
        if isinstance(end, datetime) and end.date() == start.date():
            when = f"{when}–{end.strftime(fmt)}"
    else:
        when = ""
    return {
        "uid": ev.get("uid"),
        "title": ev.get("summary") or "(no title)",
        "when": when,
        "start_iso": start.isoformat() if isinstance(start, datetime) else None,
        "end_iso": end.isoformat() if isinstance(end, datetime) else None,
        "location": ev.get("location"),
        "all_day": bool(ev.get("all_day")),
    }


def calendar_load(*, force_fetch: bool = False, horizon_days: int = 2) -> dict[str, Any]:
    """Return calendar summary when an iCal URL is configured; never raises."""
    if not configured():
        return {"available": False, "reason": "not_configured"}

    try:
        from friday.calendar.fetch import cached_body, fetch_ical
        from friday.calendar.ical_parse import parse_ics

        from_cache = False
        try:
            body, from_cache = fetch_ical(force=force_fetch)
        except RuntimeError:
            body = cached_body()
            from_cache = True
            if not body:
                raise
        events = parse_ics(body, expand_days=max(horizon_days, 7))
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "reason": "load_failed", "error": str(exc)[:160]}

    now = datetime.now().astimezone()
    today = now.date()
    tomorrow = today + timedelta(days=1)
    today_ev: list[dict[str, Any]] = []
    upcoming: list[dict[str, Any]] = []

    for ev in events:
        start = ev.get("start")
        if not isinstance(start, datetime):
            continue
        local_start = start.astimezone()
        if local_start.date() == today:
            today_ev.append(_serialize_event(ev))
        elif local_start.date() == tomorrow and len(upcoming) < 6:
            upcoming.append(_serialize_event(ev))
        elif local_start > now and len(upcoming) < 8:
            upcoming.append(_serialize_event(ev))

    today_ev.sort(key=lambda e: e.get("start_iso") or "")
    upcoming.sort(key=lambda e: e.get("start_iso") or "")

    return {
        "available": True,
        "from_cache": from_cache,
        "event_count_today": len(today_ev),
        "events_today": today_ev[:12],
        "next_events": (today_ev + upcoming)[:6],
        "summary": _summary_line(today_ev, upcoming),
    }


def _summary_line(today_ev: list[dict[str, Any]], upcoming: list[dict[str, Any]]) -> str:
    if not today_ev and not upcoming:
        return "No calendar events in the next day or so."
    if today_ev:
        titles = ", ".join(e["title"][:40] for e in today_ev[:4])
        extra = len(today_ev) - min(4, len(today_ev))
        if extra > 0:
            titles += f" (+{extra} more today)"
        return f"Today on the calendar: {titles}."
    n = upcoming[0]
    return f"Next up: {n.get('title', 'event')} ({n.get('when') or 'soon'})."
