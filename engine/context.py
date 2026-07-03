"""
Compress growing action history so the VLM prompt stays small.

Summarization is text-only (no images) to avoid VRAM spikes.
"""

from __future__ import annotations

from config import CONTEXT_RECENT_ACTIONS, CONTEXT_SUMMARIZE_EVERY
from engine.session import TaskSession


_SUMMARIZE_PROMPT = """You are a context compressor for a desktop automation agent.
Summarize the action history below into 3–6 concise bullet points.
Preserve: apps opened, dialogs dismissed, errors, current progress toward the goal.
Omit: redundant retries, coordinate details, filler.
Return ONLY the bullet list, no preamble."""


def should_summarize(session: TaskSession) -> bool:
    if CONTEXT_SUMMARIZE_EVERY <= 0:
        return False
    return (
        len(session.history) >= CONTEXT_SUMMARIZE_EVERY
        and len(session.history) % CONTEXT_SUMMARIZE_EVERY == 0
    )


def maybe_summarize_context(session: TaskSession) -> None:
    """If due, replace old history with a rolling summary + recent raw entries."""
    if not should_summarize(session):
        return

    from engine.local_model import query_model_text

    older = session.history[:-CONTEXT_RECENT_ACTIONS]
    if not older:
        return

    prompt = (
        f"{_SUMMARIZE_PROMPT}\n\n"
        f"TASK: {session.objective}\n\n"
        f"CURRENT PHASE: {(session.current_phase or {}).get('title', '?')}\n\n"
        f"PRIOR SUMMARY:\n{session.context_summary or '(none)'}\n\n"
        f"ACTIONS TO COMPRESS:\n" + "\n".join(older)
    )

    print("[Friday] Summarizing context to save memory...")
    result = query_model_text(prompt, format_json=False)
    summary = (result.get("message") or result.get("text") or "").strip()

    if not summary and isinstance(result.get("raw"), str):
        summary = result["raw"].strip()

    if summary:
        session.context_summary = summary
        session.history = session.history[-CONTEXT_RECENT_ACTIONS:]
        print(f"[Friday] Context compressed ({len(older)} actions → summary).")
