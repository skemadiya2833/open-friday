"""Reminders / notifications, the full memory overview, and chat clearing."""

from __future__ import annotations

import time
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
    """One list of everything Friday remembers, whatever put it there, each entry tagged with its source."""
    items: list[dict[str, Any]] = []
    errors: list[str] = []

    try:
        from friday.memory import get_memory

        for coll in ("memories", "conversation_chunks"):
            for h in get_memory().list_all(collection=coll, limit=limit):
                md = h.metadata or {}
                src = str(md.get("source") or ("you" if coll == "memories" else "chat"))
                kind = {"auto": "learned", "computer_use": "desktop", "you": "note", "chat": "chat"}.get(src, "note")
                items.append({"id": h.id, "collection": coll, "kind": kind, "source": src, "text": h.text,
                              "created_at": float(md.get("created_at", 0) or 0), "deletable": True})
    except Exception as exc:  # noqa: BLE001
        errors.append(f"memory: {exc}")

    try:
        from friday.experience.store import get_experience

        for e in get_experience().list_entries(limit=limit):
            items.append({"id": e["id"], "collection": e["collection"], "kind": "experience", "source": "desktop agent",
                          "text": e.get("text", ""), "created_at": float(e.get("created_at", 0) or 0), "deletable": False})
    except Exception as exc:  # noqa: BLE001
        errors.append(f"experience: {exc}")

    try:
        from friday.tasks.plan import get_plan

        for it in get_plan().get("items") or []:
            items.append({"id": it.get("id", ""), "collection": "plan", "kind": "plan", "source": "today's plan",
                          "text": ("✓ " if it.get("done") else "") + it.get("text", ""), "created_at": 0, "deletable": False})
    except Exception as exc:  # noqa: BLE001
        errors.append(f"plan: {exc}")

    try:
        from friday.assistant.session import get_session_store

        for s in get_session_store().list_sessions(20):
            full = get_session_store().load(s["id"])
            if not full:
                continue
            for t in full.turns[-30:]:
                items.append({
                    "id": f"{s['id']}:{t.ts}",
                    "collection": "conversations",
                    "kind": "chat",
                    "source": "you said" if t.role == "user" else "Friday said",
                    "text": (t.content or "")[:500],
                    "created_at": float(t.ts or 0),
                    "deletable": False,
                })
    except Exception as exc:  # noqa: BLE001
        errors.append(f"chat: {exc}")

    try:
        from friday.tasks.scheduler import get_scheduler

        for j in get_scheduler().list_jobs():
            if j["status"] in ("scheduled", "paused"):
                items.append({"id": j["id"], "collection": "jobs", "kind": "reminder", "source": "scheduler",
                              "text": f"{j['title']} ({'repeats ' + j['cron'] if j['cron'] else time.strftime('%a %d %b %H:%M', time.localtime(j['run_at'] or 0))})",
                              "created_at": float(j.get("created_at") or 0), "deletable": False})
    except Exception as exc:  # noqa: BLE001
        errors.append(f"jobs: {exc}")

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
