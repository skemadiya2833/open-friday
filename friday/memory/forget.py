"""Forget one memory entry or everything Friday is showing in Memory Core."""

from __future__ import annotations


def forget_entry(collection: str, doc_id: str) -> bool:
    coll = (collection or "memories").strip()
    doc_id = (doc_id or "").strip()
    if not doc_id:
        return False

    if coll in ("owner_facts", "memories"):
        from friday.store.facts import delete_fact

        if delete_fact(doc_id):
            return True
        if coll == "memories":
            from friday.memory import get_memory

            return get_memory().delete(doc_id, collection="memories")
        return False

    if coll == "conversation_chunks":
        # Deprecated — chat is not memory. Best-effort chroma cleanup only.
        from friday.memory import get_memory

        return get_memory().delete(doc_id, collection=coll)

    if coll == "plan":
        from friday.tasks.plan import remove_item

        return remove_item(doc_id)

    if coll == "jobs":
        from friday.tasks.scheduler import get_scheduler

        return get_scheduler().cancel(doc_id)

    if coll == "conversations":
        # Chat transcripts are no longer listed in Memory; keep delete_turn for old clients.
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
    """Wipe structured Memory Core stores. Does not wipe chat session history."""
    counts: dict[str, int] = {}

    try:
        from friday.store.facts import clear_facts

        counts["facts"] = clear_facts()
    except Exception:
        counts["facts"] = 0

    try:
        from friday.memory import get_memory

        mem = get_memory()
        n = 0
        for h in mem.list_all(collection="memories", limit=5000):
            if mem.delete(h.id, collection="memories"):
                n += 1
        counts["chroma_notes"] = n
    except Exception:
        counts["chroma_notes"] = 0

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

    return counts


def overview_item_deletable(_kind: str) -> bool:
    return True
