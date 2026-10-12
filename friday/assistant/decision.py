"""Structured decision helper — two options, tradeoffs, owner needs."""

from __future__ import annotations

from typing import Any


def build_decision(
    *,
    question: str,
    option_a: str,
    option_b: str,
    context: str = "",
    recommendation: str | None = None,
    cost_of_delay: str | None = None,
    needs_from_owner: list[str] | None = None,
) -> dict[str, Any]:
    question = (question or "").strip()
    option_a = (option_a or "").strip()
    option_b = (option_b or "").strip()
    if not question or not option_a or not option_b:
        raise ValueError("question, option_a, and option_b are required")

    rec = (recommendation or "").strip()
    if not rec:
        rec = f"If you want a default, '{option_a[:60]}' is slightly lighter to reverse — but either works."

    delay = (cost_of_delay or "").strip()
    if not delay:
        delay = "Waiting may keep the question open; only matters if a deadline is real."

    needs = needs_from_owner or []
    if not needs:
        needs = ["Which option matches your energy and deadline?", "Anything I should assume before acting?"]

    return {
        "question": question[:500],
        "context": (context or "")[:800],
        "options": [
            {"id": "a", "label": option_a[:300]},
            {"id": "b", "label": option_b[:300]},
        ],
        "recommendation": rec[:400],
        "cost_of_delay": delay[:400],
        "needs_from_owner": [n[:200] for n in needs[:6]],
        "tone": "collaborative",
        "escalation": False,
    }
