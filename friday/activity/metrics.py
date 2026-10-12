"""Productivity metrics from ActivityWatch or local logger events (pure numbers)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

_FOCUS_MIN = 25 * 60
_MEETING_CATS = frozenset({"communication", "meeting"})
_DEEP_CATS = frozenset({"deep_work", "development", "code"})


def _total_active(events: list[dict[str, Any]]) -> float:
    return sum(max(0.0, float(e.get("duration") or 0)) for e in events)


def _cat_seconds(events: list[dict[str, Any]]) -> dict[str, float]:
    out: dict[str, float] = {}
    for e in events:
        cat = (e.get("category") or "uncategorized").strip() or "uncategorized"
        out[cat] = out.get(cat, 0.0) + max(0.0, float(e.get("duration") or 0))
    return out


def focus_blocks(events: list[dict[str, Any]], *, min_seconds: float = _FOCUS_MIN) -> list[dict[str, Any]]:
    """Merge consecutive same-app events into focus blocks."""
    if not events:
        return []
    ordered = sorted(events, key=lambda e: float(e.get("start") or 0))
    blocks: list[dict[str, Any]] = []
    cur_app = ""
    cur_start = 0.0
    cur_end = 0.0
    for e in ordered:
        app = (e.get("app") or "").lower()
        start = float(e.get("start") or 0)
        end = start + max(0.0, float(e.get("duration") or 0))
        if app and app == cur_app and start <= cur_end + 120:
            cur_end = max(cur_end, end)
            continue
        if cur_app and (cur_end - cur_start) >= min_seconds:
            blocks.append(
                {
                    "app": cur_app,
                    "start": cur_start,
                    "end": cur_end,
                    "duration_seconds": cur_end - cur_start,
                }
            )
        cur_app, cur_start, cur_end = app, start, end
    if cur_app and (cur_end - cur_start) >= min_seconds:
        blocks.append(
            {
                "app": cur_app,
                "start": cur_start,
                "end": cur_end,
                "duration_seconds": cur_end - cur_start,
            }
        )
    return blocks


def compute_metrics(
    events: list[dict[str, Any]],
    *,
    prior_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    total = _total_active(events)
    alloc = _cat_seconds(events)
    meeting = sum(alloc.get(c, 0.0) for c in alloc if c in _MEETING_CATS or "meet" in c)
    deep = sum(alloc.get(c, 0.0) for c in alloc if c in _DEEP_CATS)
    uncategorized = alloc.get("uncategorized", 0.0)
    blocks = focus_blocks(events)
    focus_seconds = sum(b["duration_seconds"] for b in blocks)
    deep_work_ratio = round(deep / total, 4) if total > 0 else 0.0
    meeting_load = round(meeting / total, 4) if total > 0 else 0.0

    trends: dict[str, Any] = {}
    if prior_events is not None:
        prior_total = _total_active(prior_events)
        prior_deep = sum(_cat_seconds(prior_events).get(c, 0.0) for c in _DEEP_CATS)
        trends = {
            "active_seconds_delta": round(total - prior_total, 2),
            "deep_work_seconds_delta": round(deep - prior_deep, 2),
            "deep_work_ratio_delta": round(
                (deep / total if total else 0) - (prior_deep / prior_total if prior_total else 0),
                4,
            ),
        }

    return {
        "active_seconds": round(total, 2),
        "time_allocation_seconds": {k: round(v, 2) for k, v in sorted(alloc.items(), key=lambda x: -x[1])},
        "focus_block_count": len(blocks),
        "focus_seconds": round(focus_seconds, 2),
        "meeting_seconds": round(meeting, 2),
        "meeting_load_ratio": meeting_load,
        "deep_work_seconds": round(deep, 2),
        "deep_work_ratio": deep_work_ratio,
        "uncategorized_seconds": round(uncategorized, 2),
        "focus_blocks": blocks[:48],
        "trends": trends,
    }


def gather_events_for_range(
    *,
    start: datetime,
    end: datetime,
    prefer_aw: bool = True,
) -> tuple[list[dict[str, Any]], str]:
    """Load normalized events; returns (events, source_label)."""
    from friday.activity.aw import ActivityWatchClient, load_approved_rules, normalize_aw_event
    from friday.activity import local_logger

    rules = load_approved_rules()
    if prefer_aw:
        client = ActivityWatchClient()
        if client.probe().get("available"):
            raw = client.fetch_window_events(start=start, end=end)
            evs = [normalize_aw_event(e, rules=rules) for e in raw]
            if evs:
                return evs, "activitywatch"
    since = start.timestamp()
    until = end.timestamp()
    samples = local_logger.read_samples(since=since, until=until)
    if samples:
        return local_logger.samples_to_events(samples), "local"
    return [], "none"
