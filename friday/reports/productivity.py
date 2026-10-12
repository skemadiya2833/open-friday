"""Productivity visual report catalog — computed charts + guarded commentary slot."""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from friday.reports.commentary_guard import validate_commentary


REPORT_CATALOG = [
    "week_heatmap",
    "time_allocation_bars",
    "focus_block_timeline",
    "meeting_vs_deep_work",
    "open_loops",
    "weekly_chief_of_staff_summary",
]


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _bar_series(alloc: dict[str, float], *, source_id: str = "metrics") -> list[dict[str, Any]]:
    series: list[dict[str, Any]] = []
    for label, seconds in list(alloc.items())[:12]:
        val = round(seconds / 3600, 2) if seconds else 0.0
        series.append(
            {
                "label": label[:80],
                "value": val,
                "source_id": source_id,
                "snippet": f"{label} {seconds} seconds",
            }
        )
    return series


def _week_heatmap_cells(events: list[dict[str, Any]], *, period_start: float) -> list[dict[str, Any]]:
    cells: list[dict[str, Any]] = []
    start_dt = datetime.fromtimestamp(period_start, tz=timezone.utc)
    for ev in events:
        ts = float(ev.get("start") or 0)
        dur = max(0.0, float(ev.get("duration") or 0))
        if dur <= 0:
            continue
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        row = (dt.date() - start_dt.date()).days
        if row < 0 or row > 6:
            continue
        col = dt.hour
        cells.append({"row": row, "col": col, "value": round(dur / 3600, 3)})
    return cells


def build_productivity_report(
    metrics: dict[str, Any],
    *,
    events: list[dict[str, Any]] | None = None,
    period_days: int = 7,
    commentary: str = "",
    open_loops: list[str] | None = None,
) -> dict[str, Any]:
    events = events or []
    now = time.time()
    period_start = now - period_days * 86400
    rid = uuid.uuid4().hex[:16]
    alloc = metrics.get("time_allocation_seconds") or {}
    charts: list[dict[str, Any]] = [
        {
            "id": "week_heatmap",
            "title": "Active hours (week heatmap)",
            "kind": "heatmap",
            "grid": {"rows": min(7, period_days), "cols": 24, "cells": _week_heatmap_cells(events, period_start=period_start)},
            "series": [],
        },
        {
            "id": "time_allocation",
            "title": "Time allocation (hours)",
            "kind": "bar",
            "series": _bar_series(alloc),
        },
        {
            "id": "focus_timeline",
            "title": "Focus blocks (25m+)",
            "kind": "timeline",
            "blocks": [
                {
                    "start": _iso(float(b.get("start") or 0)),
                    "end": _iso(float(b.get("end") or 0)),
                    "label": b.get("app") or "focus",
                    "duration_seconds": b.get("duration_seconds"),
                }
                for b in (metrics.get("focus_blocks") or [])[:24]
            ],
            "series": [],
        },
        {
            "id": "meeting_vs_deep",
            "title": "Meeting vs deep work (hours)",
            "kind": "bar",
            "series": [
                {
                    "label": "meetings",
                    "value": round(float(metrics.get("meeting_seconds") or 0) / 3600, 2),
                    "source_id": "metrics",
                    "snippet": f"meeting_seconds {metrics.get('meeting_seconds')}",
                },
                {
                    "label": "deep work",
                    "value": round(float(metrics.get("deep_work_seconds") or 0) / 3600, 2),
                    "source_id": "metrics",
                    "snippet": f"deep_work_seconds {metrics.get('deep_work_seconds')}",
                },
            ],
        },
    ]

    loops = open_loops or []
    guard_ok, invented = validate_commentary(commentary, metrics)
    doc: dict[str, Any] = {
        "schema_version": "productivity-1",
        "id": rid,
        "kind": "productivity",
        "catalog": REPORT_CATALOG,
        "period_days": period_days,
        "period_start": _iso(period_start),
        "period_end": _iso(now),
        "created_at": _iso(now),
        "metrics": metrics,
        "charts": charts,
        "open_loops": loops[:32],
        "commentary": commentary,
        "commentary_valid": guard_ok,
        "commentary_issues": [f"invented number: {n}" for n in invented],
        "summary": {
            "tldr": "",
            "confidence": 1.0 if guard_ok else 0.0,
            "rationale": "Numbers in commentary must match computed metrics.",
        },
    }
    return doc


def build_weekly_chief_of_staff_summary(metrics: dict[str, Any], *, open_loops: list[str]) -> str:
    """Template summary using only metric numbers (no model required)."""
    parts = [
        f"Active time: {metrics.get('active_seconds')}s over the period.",
        f"Deep work ratio: {metrics.get('deep_work_ratio')}; meeting load: {metrics.get('meeting_load_ratio')}.",
        f"Focus blocks: {metrics.get('focus_block_count')} totaling {metrics.get('focus_seconds')}s.",
    ]
    if open_loops:
        parts.append(f"Open loops captured: {len(open_loops)}.")
    return " ".join(parts)


def assemble_full_report(
    *,
    period_days: int = 7,
    commentary: str = "",
) -> dict[str, Any]:
    from friday.activity.metrics import compute_metrics, gather_events_for_range
    from friday.assistant.inbox import list_items

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=period_days)
    prior_start = start - timedelta(days=period_days)
    events, source = gather_events_for_range(start=start, end=end)
    prior, _ = gather_events_for_range(start=prior_start, end=start, prefer_aw=source == "activitywatch")
    metrics = compute_metrics(events, prior_events=prior if prior else None)
    loops = [(i.get("text") or "").strip() for i in list_items(limit=20, status="open")]
    loops = [t for t in loops if t]
    if not commentary:
        commentary = build_weekly_chief_of_staff_summary(metrics, open_loops=loops)
    doc = build_productivity_report(
        metrics,
        events=events,
        period_days=period_days,
        commentary=commentary,
        open_loops=loops,
    )
    doc["data_source"] = source
    return doc
