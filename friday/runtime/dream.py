"""Opt-in dream / diary synthesis notes (Valkyrill / Crescent-inspired).

When ``dream_mode`` Systems pref is on, append a short diary entry —
never silent Chroma / experience writes.
"""

from __future__ import annotations

from typing import Any


def maybe_append_dream_note(summary: str) -> dict[str, Any] | None:
    from friday.runtime.prefs import get as pref_get

    if not pref_get("dream_mode"):
        return None
    text = (summary or "").strip()
    if not text:
        return None
    from friday.runtime.diary import record

    try:
        path = record("Dream proposal", text[:400], kind="dream")
        return {"ok": True, "path": path}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
