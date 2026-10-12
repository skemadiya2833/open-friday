"""Activity awareness API — ActivityWatch probe, rules, consent, productivity reports."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(tags=["activity"])


class ConsentBody(BaseModel):
    enabled: bool


class ApproveRulesBody(BaseModel):
    rules: list[dict[str, Any]] = Field(default_factory=list)


class CommentaryBody(BaseModel):
    commentary: str = Field("", max_length=4000)
    period_days: int = Field(7, ge=1, le=30)


@router.get("/api/activity/status")
def activity_status() -> dict[str, Any]:
    from friday.activity.aw import ActivityWatchClient, load_approved_rules
    from friday.activity import local_logger

    aw = ActivityWatchClient().probe()
    return {
        "activitywatch": aw,
        "local_logger": local_logger.status(),
        "rules_count": len(load_approved_rules()),
    }


@router.get("/api/activity/aw/buckets")
def activity_aw_buckets() -> dict[str, Any]:
    from friday.activity.aw import ActivityWatchClient

    return ActivityWatchClient().list_buckets()


@router.get("/api/activity/aw/events")
def activity_aw_events(days: int = 7) -> dict[str, Any]:
    from friday.activity.aw import ActivityWatchClient, load_approved_rules, normalize_aw_event, suggest_categorization_rules

    days = max(1, min(days, 30))
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    client = ActivityWatchClient()
    if not client.probe().get("available"):
        return {"available": False, "events": [], "suggested_rules": []}
    raw = client.fetch_window_events(start=start, end=end)
    rules = load_approved_rules()
    events = [normalize_aw_event(e, rules=rules) for e in raw]
    return {
        "available": True,
        "events": events[:500],
        "suggested_rules": suggest_categorization_rules(raw),
        "approved_rules": rules,
    }


@router.get("/api/activity/aw/rules")
def activity_rules_get() -> dict[str, Any]:
    from friday.activity.aw import load_approved_rules, suggest_categorization_rules, ActivityWatchClient

    rules = load_approved_rules()
    suggestions: list[dict[str, Any]] = []
    client = ActivityWatchClient()
    if client.probe().get("available"):
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=7)
        raw = client.fetch_window_events(start=start, end=end)
        suggestions = suggest_categorization_rules(raw)
    return {"approved_rules": rules, "suggested_rules": suggestions}


@router.post("/api/activity/aw/rules/approve")
def activity_rules_approve(body: ApproveRulesBody) -> dict[str, Any]:
    from friday.activity.aw import approve_rules

    approved = approve_rules(body.rules)
    return {"approved_rules": approved}


@router.get("/api/activity/consent")
def activity_consent_get() -> dict[str, Any]:
    from friday.activity import local_logger

    return local_logger.load_consent()


@router.post("/api/activity/consent")
def activity_consent_set(body: ConsentBody) -> dict[str, Any]:
    from friday.activity import local_logger

    return local_logger.set_consent(body.enabled)


@router.post("/api/activity/local/sample")
def activity_local_sample() -> dict[str, Any]:
    from friday.activity import local_logger

    if not local_logger.consent_enabled():
        raise HTTPException(403, "Local activity logging requires explicit consent")
    row = local_logger.sample_once()
    if not row:
        return {"sampled": False, "reason": "excluded_or_idle"}
    return {"sampled": True, "row": row}


@router.delete("/api/activity/local/all")
def activity_local_delete_all() -> dict[str, Any]:
    from friday.activity import local_logger

    return local_logger.delete_all()


@router.get("/api/activity/metrics")
def activity_metrics(days: int = 7) -> dict[str, Any]:
    from friday.activity.metrics import compute_metrics, gather_events_for_range

    days = max(1, min(days, 30))
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    prior_start = start - timedelta(days=days)
    events, source = gather_events_for_range(start=start, end=end)
    prior, _ = gather_events_for_range(start=prior_start, end=start, prefer_aw=source == "activitywatch")
    metrics = compute_metrics(events, prior_events=prior if prior else None)
    return {"source": source, "metrics": metrics}


@router.get("/api/activity/reports/productivity")
def activity_productivity_report(days: int = 7) -> dict[str, Any]:
    from friday.reports.productivity import assemble_full_report

    return assemble_full_report(period_days=max(1, min(days, 30)))


@router.post("/api/activity/reports/productivity/commentary")
def activity_productivity_commentary(body: CommentaryBody) -> dict[str, Any]:
    from friday.activity.metrics import compute_metrics, gather_events_for_range
    from friday.assistant.inbox import list_items
    from friday.reports.productivity import build_productivity_report

    days = body.period_days
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    prior_start = start - timedelta(days=days)
    events, source = gather_events_for_range(start=start, end=end)
    prior, _ = gather_events_for_range(start=prior_start, end=start, prefer_aw=source == "activitywatch")
    metrics = compute_metrics(events, prior_events=prior if prior else None)
    loops = [(i.get("text") or "").strip() for i in list_items(limit=20, status="open")]
    loops = [t for t in loops if t]
    doc = build_productivity_report(
        metrics,
        events=events,
        period_days=days,
        commentary=body.commentary,
        open_loops=loops,
    )
    doc["data_source"] = source
    if not doc.get("commentary_valid"):
        raise HTTPException(422, detail={"issues": doc.get("commentary_issues")})
    return doc
