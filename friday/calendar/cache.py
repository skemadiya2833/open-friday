"""SQLite cache of parsed calendar events (structured store; iCal remains the source)."""

from __future__ import annotations

import time
from datetime import date, datetime
from typing import Any

from friday.store.db import connect, ensure_schema

# Refetch iCal when cache is older than this (seconds).
CACHE_TTL_SECONDS = 15 * 60


def _ts(dt: datetime) -> float:
    if dt.tzinfo is None:
        return dt.timestamp()
    return dt.timestamp()


def upsert_events(events: list[dict[str, Any]]) -> int:
    """Replace cache with freshly parsed events. Returns count stored."""
    ensure_schema()
    now = time.time()
    with connect() as conn:
        conn.execute("DELETE FROM calendar_events")
        n = 0
        for ev in events:
            start = ev.get("start")
            end = ev.get("end")
            if not isinstance(start, datetime) or not isinstance(end, datetime):
                continue
            uid = str(ev.get("uid") or f"anon-{n}-{int(_ts(start))}")
            raw_day = start.astimezone().date().isoformat() if start.tzinfo else start.date().isoformat()
            conn.execute(
                """
                INSERT OR REPLACE INTO calendar_events
                (uid, start_ts, end_ts, summary, location, all_day, raw_day, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uid,
                    _ts(start),
                    _ts(end),
                    str(ev.get("summary") or "")[:300],
                    str(ev.get("location") or "")[:200],
                    1 if ev.get("all_day") else 0,
                    raw_day,
                    now,
                ),
            )
            n += 1
        conn.commit()
    return n


def cache_age_seconds() -> float | None:
    ensure_schema()
    with connect() as conn:
        row = conn.execute("SELECT MAX(updated_at) AS u FROM calendar_events").fetchone()
    if not row or row["u"] is None:
        return None
    return max(0.0, time.time() - float(row["u"]))


def is_fresh(*, ttl: float = CACHE_TTL_SECONDS) -> bool:
    age = cache_age_seconds()
    return age is not None and age <= ttl


def events_for_day(day: date | None = None) -> list[dict[str, Any]]:
    d = (day or date.today()).isoformat()
    ensure_schema()
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT uid, start_ts, end_ts, summary, location, all_day, raw_day
            FROM calendar_events
            WHERE raw_day = ?
            ORDER BY start_ts ASC
            """,
            (d,),
        ).fetchall()
    return [_row_to_event(r) for r in rows]


def events_in_range(start_ts: float, end_ts: float) -> list[dict[str, Any]]:
    ensure_schema()
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT uid, start_ts, end_ts, summary, location, all_day, raw_day
            FROM calendar_events
            WHERE end_ts > ? AND start_ts < ?
            ORDER BY start_ts ASC
            """,
            (start_ts, end_ts),
        ).fetchall()
    return [_row_to_event(r) for r in rows]


def _row_to_event(r: Any) -> dict[str, Any]:
    start = datetime.fromtimestamp(float(r["start_ts"])).astimezone()
    end = datetime.fromtimestamp(float(r["end_ts"])).astimezone()
    return {
        "uid": r["uid"],
        "summary": r["summary"] or "",
        "start": start,
        "end": end,
        "location": r["location"] or None,
        "all_day": bool(r["all_day"]),
        "raw_day": r["raw_day"],
    }


def refresh_from_ical(*, force: bool = False) -> dict[str, Any]:
    """Fetch/parse iCal into SQLite when stale or forced."""
    from friday.calendar.secrets import configured

    if not configured():
        return {"ok": False, "reason": "not_configured", "count": 0}
    if not force and is_fresh():
        return {"ok": True, "reason": "fresh", "count": len(events_for_day())}
    try:
        from friday.calendar.fetch import cached_body, fetch_ical
        from friday.calendar.ical_parse import parse_ics

        try:
            body, from_cache = fetch_ical(force=force)
        except RuntimeError:
            body = cached_body()
            from_cache = True
            if not body:
                raise
        parsed = parse_ics(body, expand_days=14)
        n = upsert_events(parsed)
        return {"ok": True, "reason": "refreshed", "count": n, "from_cache": from_cache}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": "load_failed", "error": str(exc)[:160], "count": 0}


def today_lines(*, force: bool = False, limit: int = 12) -> list[str]:
    """Human lines for day-plan / prompts. Empty list when nothing useful."""
    refresh_from_ical(force=force)
    lines: list[str] = []
    for ev in events_for_day()[:limit]:
        title = (ev.get("summary") or "Event").strip()
        start = ev.get("start")
        if ev.get("all_day"):
            lines.append(f"all day — {title}")
        elif isinstance(start, datetime):
            when = start.strftime("%H:%M")
            lines.append(f"{when} — {title}")
        else:
            lines.append(title)
    return lines
