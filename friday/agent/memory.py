"""Compress growing action history so prompts stay small."""

from __future__ import annotations

from friday.agent.session import AgentSession
from friday.config import CONTEXT_RECENT_ACTIONS, CONTEXT_SUMMARIZE_EVERY

def maybe_summarize_context(session: AgentSession) -> None:
    if CONTEXT_SUMMARIZE_EVERY <= 0:
        return
    if len(session.history) < CONTEXT_SUMMARIZE_EVERY:
        return
    if len(session.history) % CONTEXT_SUMMARIZE_EVERY != 0:
        return

    from friday.models.local import query_model_text
    from friday.prompts import context_summarize_prompt

    older = session.history[:-CONTEXT_RECENT_ACTIONS]
    if not older:
        return

    prompt = context_summarize_prompt(
        objective=session.objective,
        prior=session.context_summary or "",
        actions="\n".join(older),
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
