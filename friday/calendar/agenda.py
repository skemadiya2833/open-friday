"""Agenda helpers over parsed calendar events."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from friday.calendar.fetch import fetch_ical
from friday.calendar.ical_parse import Event, parse_ics

EventDict = dict[str, Any]

_UI_NOTE = (
    "Editing or deleting existing events requires the Google Calendar API or browser automation; "
    "Friday only proposes new slots and opens Calendar views."
)


def ui_note() -> str:
    return _UI_NOTE


def _serialize_event(e: Event) -> EventDict:
    return {
        "uid": e["uid"],
        "summary": e["summary"],
        "start": e["start"].isoformat(),
        "end": e["end"].isoformat(),
        "location": e.get("location"),
        "description": e.get("description"),
        "attendees": e.get("attendees") or [],
        "status": e.get("status"),
        "all_day": bool(e.get("all_day")),
    }


def load_events(*, force_fetch: bool = False) -> list[Event]:
    """Prefer SQLite calendar cache; refresh from iCal when stale or forced."""
    try:
        from friday.calendar.cache import events_in_range, refresh_from_ical

        refresh_from_ical(force=force_fetch)
        # Wide window: past day through +14d for free-slots / week views
        now = datetime.now().astimezone()
        start = now - timedelta(days=1)
        end = now + timedelta(days=14)
        rows = events_in_range(start.timestamp(), end.timestamp())
        out: list[Event] = []
        for r in rows:
            out.append(
                {
                    "uid": r["uid"],
                    "summary": r.get("summary") or "",
                    "start": r["start"],
                    "end": r["end"],
                    "location": r.get("location"),
                    "description": None,
                    "attendees": [],
                    "status": None,
                    "all_day": bool(r.get("all_day")),
                }
            )
        if out or not force_fetch:
            return out
    except Exception:  # noqa: BLE001
        pass
    body, _from_cache = fetch_ical(force=force_fetch)
    return parse_ics(body)


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    tz = datetime.now().astimezone().tzinfo
    start = datetime.combine(day, time.min, tzinfo=tz)
    end = start + timedelta(days=1)
    return start, end


def _filter_range(events: list[Event], start: datetime, end: datetime) -> list[Event]:
    out: list[Event] = []
    for e in events:
        if e["end"] <= start or e["start"] >= end:
            continue
        out.append(e)
    return out


def today_agenda(*, force_fetch: bool = False) -> dict[str, Any]:
    today = date.today()
    start, end = _day_bounds(today)
    events = _filter_range(load_events(force_fetch=force_fetch), start, end)
    return {
        "range": "today",
        "date": today.isoformat(),
        "events": [_serialize_event(e) for e in events],
        "note": _UI_NOTE,
    }


def week_agenda(*, force_fetch: bool = False) -> dict[str, Any]:
    today = date.today()
    tz = datetime.now().astimezone().tzinfo
    week_start = today - timedelta(days=today.weekday())
    start = datetime.combine(week_start, time.min, tzinfo=tz)
    end = start + timedelta(days=7)
    events = _filter_range(load_events(force_fetch=force_fetch), start, end)
    return {
        "range": "week",
        "week_start": week_start.isoformat(),
        "events": [_serialize_event(e) for e in events],
        "note": _UI_NOTE,
    }


def next_event(*, force_fetch: bool = False) -> dict[str, Any]:
    now = datetime.now().astimezone()
    upcoming = [e for e in load_events(force_fetch=force_fetch) if e["end"] > now]
    upcoming.sort(key=lambda e: e["start"])
    ev = upcoming[0] if upcoming else None
    return {
        "event": _serialize_event(ev) if ev else None,
        "note": _UI_NOTE,
    }


def free_slots(day: date, duration_min: int, *, force_fetch: bool = False) -> list[dict[str, str]]:
    """Return free windows on *day* long enough for *duration_min* (default workday 09–18)."""
    duration = timedelta(minutes=max(1, duration_min))
    tz = datetime.now().astimezone().tzinfo
    day_start = datetime.combine(day, time(9, 0), tzinfo=tz)
    day_end = datetime.combine(day, time(18, 0), tzinfo=tz)
    busy = _filter_range(load_events(force_fetch=force_fetch), day_start, day_end)
    busy.sort(key=lambda e: e["start"])

    slots: list[dict[str, str]] = []
    cursor = day_start
    for e in busy:
        if e["all_day"]:
            continue
        b_start = max(e["start"], day_start)
        b_end = min(e["end"], day_end)
        if b_end <= cursor:
            continue
        if b_start - cursor >= duration:
            slots.append({"start": cursor.isoformat(), "end": b_start.isoformat()})
        cursor = max(cursor, b_end)
    if day_end - cursor >= duration:
        slots.append({"start": cursor.isoformat(), "end": day_end.isoformat()})
    return slots


def conflicts(events: list[Event] | None = None, *, force_fetch: bool = False) -> list[dict[str, Any]]:
    evs = events if events is not None else load_events(force_fetch=force_fetch)
    evs = [e for e in evs if not e.get("all_day")]
    evs.sort(key=lambda e: e["start"])
    pairs: list[dict[str, Any]] = []
    for i, a in enumerate(evs):
        for b in evs[i + 1 :]:
            if b["start"] >= a["end"]:
                break
            if a["end"] > b["start"]:
                pairs.append({"a": _serialize_event(a), "b": _serialize_event(b)})
    return pairs


def back_to_back(events: list[Event] | None = None, *, gap_minutes: int = 5, force_fetch: bool = False) -> list[dict[str, Any]]:
    evs = events if events is not None else load_events(force_fetch=force_fetch)
    evs = [e for e in evs if not e.get("all_day")]
    evs.sort(key=lambda e: e["start"])
    gap = timedelta(minutes=gap_minutes)
    out: list[dict[str, Any]] = []
    for i in range(len(evs) - 1):
        a, b = evs[i], evs[i + 1]
        if timedelta(0) <= (b["start"] - a["end"]) <= gap:
            out.append({"first": _serialize_event(a), "second": _serialize_event(b)})
    return out


def meeting_load(day: date | None = None, *, force_fetch: bool = False) -> dict[str, Any]:
    d = day or date.today()
    start, end = _day_bounds(d)
    evs = _filter_range(load_events(force_fetch=force_fetch), start, end)
    busy_min = 0
    count = 0
    for e in evs:
        if e.get("all_day"):
            continue
        count += 1
        s = max(e["start"], start)
        en = min(e["end"], end)
        busy_min += max(0, int((en - s).total_seconds() // 60))
    window_min = 9 * 60  # 09–18
    return {
        "date": d.isoformat(),
        "meeting_count": count,
        "busy_minutes": busy_min,
        "load_ratio": round(busy_min / window_min, 3) if window_min else 0.0,
    }


def travel_buffer_suggestion(
    events: list[Event] | None = None,
    *,
    default_minutes: int = 15,
    force_fetch: bool = False,
) -> list[dict[str, Any]]:
    """Suggest buffer before events with a location after a different-location event."""
    evs = events if events is not None else load_events(force_fetch=force_fetch)
    evs = [e for e in evs if not e.get("all_day")]
    evs.sort(key=lambda e: e["start"])
    suggestions: list[dict[str, Any]] = []
    for i in range(1, len(evs)):
        prev, cur = evs[i - 1], evs[i]
        pl = (prev.get("location") or "").strip()
        cl = (cur.get("location") or "").strip()
        if not cl:
            continue
        if pl and pl.lower() != cl.lower():
            gap = cur["start"] - prev["end"]
            if gap < timedelta(minutes=default_minutes):
                suggestions.append(
                    {
                        "event": _serialize_event(cur),
                        "after": _serialize_event(prev),
                        "suggested_buffer_minutes": default_minutes,
                        "message": f"Allow ~{default_minutes} min travel between locations",
                    }
                )
    return suggestions
