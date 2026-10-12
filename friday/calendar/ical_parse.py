"""Minimal RFC 5545 iCalendar parser (VEVENT + limited RRULE). No icalendar dependency."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

Event = dict[str, Any]

_WEEKDAY_MAP = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
_RRULE_PART = re.compile(r"([A-Z]+)=([^;]+)")


def _local_tz():
    return datetime.now().astimezone().tzinfo or timezone.utc


def unfold_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if not raw:
            continue
        if raw.startswith((" ", "\t")) and lines:
            lines[-1] = lines[-1] + raw[1:]
        else:
            lines.append(raw)
    return lines


def _split_prop(line: str) -> tuple[str, dict[str, str], str]:
    name_part, _, value = line.partition(":")
    params: dict[str, str] = {}
    if ";" in name_part:
        base, *param_parts = name_part.split(";")
        name = base.upper()
        for pp in param_parts:
            if "=" in pp:
                k, v = pp.split("=", 1)
                params[k.upper()] = v
            else:
                params[pp.upper()] = "TRUE"
    else:
        name = name_part.upper()
    return name, params, value


def _parse_datetime(value: str, params: dict[str, str]) -> tuple[datetime, bool]:
    val = value.strip()
    all_day = params.get("VALUE", "").upper() == "DATE" or ("T" not in val and len(val) == 8)
    if all_day:
        d = datetime.strptime(val[:8], "%Y%m%d").date()
        tz = _local_tz()
        start = datetime(d.year, d.month, d.day, tzinfo=tz)
        return start, True
    if val.endswith("Z"):
        dt = datetime.strptime(val.rstrip("Z"), "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
        return dt, False
    tz = _local_tz()
    dt = datetime.strptime(val[:15], "%Y%m%dT%H%M%S").replace(tzinfo=tz)
    return dt, False


def _parse_rrule(rrule: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in _RRULE_PART.finditer(rrule.upper()):
        out[m.group(1)] = m.group(2)
    return out


def _parse_until(s: str) -> datetime:
    s = s.strip()
    if len(s) == 8:
        d = datetime.strptime(s, "%Y%m%d").date()
        tz = _local_tz()
        return datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=tz)
    if s.endswith("Z"):
        return datetime.strptime(s.rstrip("Z"), "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
    tz = _local_tz()
    return datetime.strptime(s[:15], "%Y%m%dT%H%M%S").replace(tzinfo=tz)


def _expand_rrule(
    dtstart: datetime,
    dtend: datetime,
    rrule: dict[str, str],
    *,
    horizon_days: int = 60,
) -> list[tuple[datetime, datetime]]:
    freq = rrule.get("FREQ", "WEEKLY")
    interval = max(1, int(rrule.get("INTERVAL", "1") or "1"))
    count = int(rrule["COUNT"]) if "COUNT" in rrule else None
    until = _parse_until(rrule["UNTIL"]) if "UNTIL" in rrule else None
    duration = dtend - dtstart
    now = datetime.now(dtstart.tzinfo or _local_tz())
    window_end = now + timedelta(days=horizon_days)
    if until and until < window_end:
        window_end = until
    window_start = now - timedelta(days=1)

    instances: list[tuple[datetime, datetime]] = []
    emitted = 0

    bounded = count is not None or until is not None

    def emit(start: datetime) -> bool:
        nonlocal emitted
        if count is not None and emitted >= count:
            return False
        if start > window_end:
            return False
        emitted += 1
        if bounded or start >= window_start:
            instances.append((start, start + duration))
        if count is not None and emitted >= count:
            return False
        return True

    if freq == "DAILY":
        cur = dtstart
        while cur <= window_end:
            if not emit(cur):
                break
            cur = cur + timedelta(days=interval)
        return instances

    if freq == "WEEKLY":
        byday_raw = rrule.get("BYDAY", "")
        if byday_raw:
            days = [d.strip()[:2] for d in byday_raw.split(",") if d.strip()]
            weekday_targets = {_WEEKDAY_MAP[d] for d in days if d in _WEEKDAY_MAP}
        else:
            weekday_targets = {dtstart.weekday()}

        # Walk week buckets from dtstart
        week_start = dtstart - timedelta(days=dtstart.weekday())
        week_idx = 0
        while True:
            base = week_start + timedelta(weeks=week_idx * interval)
            if base > window_end + timedelta(days=7):
                break
            for wd in sorted(weekday_targets):
                start = base + timedelta(days=wd)
                start = start.replace(
                    hour=dtstart.hour,
                    minute=dtstart.minute,
                    second=dtstart.second,
                    microsecond=dtstart.microsecond,
                )
                if start.tzinfo is None and dtstart.tzinfo:
                    start = start.replace(tzinfo=dtstart.tzinfo)
                if start < dtstart:
                    continue
                if not emit(start):
                    return instances
            week_idx += 1
            if count is not None and emitted >= count:
                break
        return instances

    if freq == "MONTHLY":
        cur = dtstart
        while cur <= window_end:
            if not emit(cur):
                break
            month = cur.month - 1 + interval
            year = cur.year + month // 12
            month = month % 12 + 1
            day = min(cur.day, _days_in_month(year, month))
            cur = cur.replace(year=year, month=month, day=day)
        return instances

    # Unknown FREQ: single instance
    instances.append((dtstart, dtend))
    return instances


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        nxt = date(year + 1, 1, 1)
    else:
        nxt = date(year, month + 1, 1)
    return (nxt - date(year, month, 1)).days


def _event_dict(
    props: dict[str, tuple[dict[str, str], str]],
    start: datetime,
    end: datetime,
    *,
    all_day: bool,
    instance_uid: str | None = None,
    attendees: list[str] | None = None,
) -> Event:
    def _val(name: str) -> str:
        if name not in props:
            return ""
        return props[name][1].strip()

    att = list(attendees or [])

    return {
        "uid": instance_uid or _val("UID") or f"anon-{start.isoformat()}",
        "summary": _val("SUMMARY") or "(no title)",
        "start": start,
        "end": end,
        "location": _val("LOCATION") or None,
        "description": _val("DESCRIPTION").replace("\\n", "\n").replace("\\,", ",") or None,
        "attendees": att,
        "status": _val("STATUS") or None,
        "all_day": all_day,
    }


def parse_ics(text: str, *, expand_days: int = 60) -> list[Event]:
    """Parse VEVENT components and expand RRULE within *expand_days* from now."""
    lines = unfold_lines(text)
    events: list[Event] = []
    i = 0
    while i < len(lines):
        if lines[i].upper() != "BEGIN:VEVENT":
            i += 1
            continue
        i += 1
        props: dict[str, tuple[dict[str, str], str]] = {}
        attendees: list[str] = []
        while i < len(lines) and lines[i].upper() != "END:VEVENT":
            name, params, value = _split_prop(lines[i])
            if name == "ATTENDEE":
                attendees.append(value.strip())
            else:
                props[name] = (params, value)
            i += 1
        if i < len(lines):
            i += 1

        if "DTSTART" not in props:
            continue
        dtstart, all_day = _parse_datetime(props["DTSTART"][1], props["DTSTART"][0])
        if "DTEND" in props:
            dtend, _ = _parse_datetime(props["DTEND"][1], props["DTEND"][0])
        elif all_day:
            dtend = dtstart + timedelta(days=1)
        else:
            dtend = dtstart + timedelta(hours=1)

        rrule_line = props.get("RRULE")
        if rrule_line:
            rule = _parse_rrule(rrule_line[1])
            for start, end in _expand_rrule(dtstart, dtend, rule, horizon_days=expand_days):
                inst_uid = f"{props.get('UID', ('', ''))[1]}-{start.strftime('%Y%m%dT%H%M%S')}"
                events.append(
                    _event_dict(
                        props,
                        start,
                        end,
                        all_day=all_day,
                        instance_uid=inst_uid,
                        attendees=attendees,
                    )
                )
        else:
            events.append(_event_dict(props, dtstart, dtend, all_day=all_day, attendees=attendees))

    events.sort(key=lambda e: e["start"])
    return events
