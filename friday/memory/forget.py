"""Forget one memory entry or everything Friday is showing in Memory Core."""

from __future__ import annotations

from typing import Any


def forget_entry(collection: str, doc_id: str) -> bool:
    coll = (collection or "memories").strip()
    doc_id = (doc_id or "").strip()
    if not doc_id:
        return False

    if coll in ("memories", "conversation_chunks"):
        from friday.memory import get_memory

        return get_memory().delete(doc_id, collection=coll)

    if coll == "plan":
        from friday.tasks.plan import remove_item

        return remove_item(doc_id)

    if coll == "jobs":
        from friday.tasks.scheduler import get_scheduler

        return get_scheduler().cancel(doc_id)

    if coll == "conversations":
        from friday.assistant.session import get_session_store

        sid, _, rest = doc_id.partition(":")
        try:
            ts = float(rest)
        except ValueError:
            return False
        return get_session_store().delete_turn(sid, ts)

    from friday.experience.store import get_experience

    return get_experience().delete(doc_id)


def forget_all() -> dict[str, int]:
    """Wipe every store the Memory Core lists. Returns counts per bucket."""
    counts: dict[str, int] = {}

    from friday.memory import get_memory

    mem = get_memory()
    n = 0
    for coll in ("memories", "conversation_chunks"):
        for h in mem.list_all(collection=coll, limit=5000):
            if mem.delete(h.id, collection=coll):
                n += 1
    counts["facts"] = n

    try:
        from friday.experience.store import get_experience

        store = get_experience()
        before = len(store.list_entries(limit=5000))
        store.clear()
        counts["experience"] = before
    except Exception:
        counts["experience"] = 0

    try:
        from friday.tasks.plan import get_plan, remove_item

        items = list(get_plan().get("items") or [])
        for it in items:
            remove_item(it.get("id") or "")
        counts["plan"] = len(items)
    except Exception:
        counts["plan"] = 0

    try:
        from friday.tasks.scheduler import get_scheduler

        sch = get_scheduler()
        n = 0
        for j in sch.list_jobs():
            if j.get("status") in ("scheduled", "paused") and sch.cancel(j["id"]):
                n += 1
        counts["reminders"] = n
    except Exception:
        counts["reminders"] = 0

    try:
        from friday.assistant.session import get_session_store

        store = get_session_store()
        n = 0
        for s in store.list_sessions(200):
            full = store.load(s["id"])
            if not full:
                continue
            n += len(full.turns)
            full.turns = []
            full.title = "New chat"
            store.save(full)
        counts["chat"] = n
    except Exception:
        counts["chat"] = 0

    return counts


def overview_item_deletable(_kind: str) -> bool:
    return True
