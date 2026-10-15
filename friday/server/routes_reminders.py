"""Reminders / notifications, the full memory overview, and chat clearing."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()


# ------------------------------------------------------------------ notifications
@router.get("/api/notifications")
def notifications(unseen: bool = False, limit: int = 50) -> list[dict[str, Any]]:
    from friday.tasks import reminders as RM

    return RM.list_notifications(unseen_only=unseen, limit=limit)


@router.get("/api/notifications/{nid}")
def notification(nid: str) -> dict[str, Any]:
    from friday.tasks import reminders as RM

    n = RM.get_notification(nid)
    if not n:
        raise HTTPException(404, "Not found")
    return n


@router.post("/api/notifications/{nid}/seen")
def notification_seen(nid: str) -> dict[str, Any]:
    from friday.tasks import reminders as RM

    return {"updated": RM.mark_seen(None if nid == "all" else nid)}


@router.post("/api/notifications/{nid}/snooze")
def notification_snooze(nid: str, minutes: int = 10) -> dict[str, Any]:
    from friday.tasks import reminders as RM
    from friday.tasks.scheduler import get_scheduler

    n = RM.get_notification(nid)
    if not n:
        raise HTTPException(404, "Not found")
    RM.mark_seen(nid)
    job = get_scheduler().add_job(prompt=n["title"], skill_id="reminder", delay_seconds=max(1, min(minutes, 24 * 60)) * 60,
                                  title=n["title"][:80])
    return {"snoozed_until": job["run_at"], "job_id": job["id"]}


@router.get("/api/reminders/upcoming")
def upcoming() -> list[dict[str, Any]]:
    from friday.tasks.scheduler import get_scheduler

    jobs = [j for j in get_scheduler().list_jobs() if j["status"] == "scheduled" and (j.get("cron") or j.get("run_at"))]
    jobs.sort(key=lambda j: j.get("run_at") or 1e18)
    return jobs


# ------------------------------------------------------------------ everything Friday knows
@router.get("/api/memory/overview")
def memory_overview(limit: int = 300) -> dict[str, Any]:
    """Structured memory only — facts, plan, reminders, experience. Chat stays in Sessions."""
    items: list[dict[str, Any]] = []
    errors: list[str] = []

    try:
        from friday.store.facts import list_facts_rows

        for row in list_facts_rows(limit=limit):
            src = str(row.get("source") or "manual")
            kind = {"auto": "learned", "computer_use": "desktop", "tool": "note", "manual": "note"}.get(src, "note")
            items.append({
                "id": row["id"],
                "collection": "owner_facts",
                "kind": kind,
                "source": src,
                "text": row["text"],
                "created_at": float(row.get("created_at") or 0),
                "deletable": True,
            })
    except Exception as exc:  # noqa: BLE001
        errors.append(f"facts: {exc}")

    try:
        from friday.experience.store import get_experience

        for e in get_experience().list_entries(limit=limit):
            items.append({"id": e["id"], "collection": e["collection"], "kind": "experience", "source": "desktop agent",
                          "text": e.get("text", ""), "created_at": float(e.get("created_at", 0) or 0), "deletable": True})
    except Exception as exc:  # noqa: BLE001
        errors.append(f"experience: {exc}")

    try:
        from friday.tasks.plan import list_plan_for_overview

        for it in list_plan_for_overview(limit=limit):
            items.append({
                "id": it.get("id", ""),
                "collection": "plan",
                "kind": "plan",
                "source": "today's plan",
                "text": it.get("text", ""),
                "created_at": float(it.get("created_at") or 0),
                "deletable": True,
            })
    except Exception as exc:  # noqa: BLE001
        errors.append(f"plan: {exc}")

    # Scheduled jobs live on Tasks — not Memory Core (they were cluttering the lattice).

    items.sort(key=lambda i: i["created_at"], reverse=True)
    counts: dict[str, int] = {}
    for i in items:
        counts[i["kind"]] = counts.get(i["kind"], 0) + 1
    return {"items": items, "counts": counts, "errors": errors}


# ------------------------------------------------------------------ chat clearing
@router.post("/api/sessions/{session_id}/clear")
def clear_session(session_id: str) -> dict[str, Any]:
    from friday.assistant.session import get_session_store

    store = get_session_store()
    s = store.load(session_id)
    if not s:
        raise HTTPException(404, "Session not found")
    n = len(s.turns)
    s.turns = []
    s.title = "New chat"
    store.save(s)
    return {"cleared": n}
