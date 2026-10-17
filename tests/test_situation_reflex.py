"""'What's going on' must not recite knowledge-graph / prompt scaffolding."""

from __future__ import annotations

from friday.assistant.reflexes import try_reflex
from friday.skills.builtin.chat.handler import _looks_like_context_dump


def test_whats_going_on_is_reflex(monkeypatch):
    monkeypatch.setattr(
        "friday.tasks.plan.get_plan",
        lambda: {"items": [{"text": "3D printing business — explore and plan", "done": False}]},
    )
    hit = try_reflex("Hey Friday what's going on")
    assert hit is not None
    assert hit.label == "situation"
    assert "previous focus" not in hit.reply.lower()
    assert "e-commerce" not in hit.reply.lower()
    assert "3D printing" in hit.reply or "agenda" in hit.reply.lower() or "Board" in hit.reply


def test_context_dump_detected():
    dump = (
        '* User: "Hey Friday what\'s going on" * Context: Saturday, Oct 17, 2026, 10:53 PM. '
        "* Agenda: [ ] 3D printing. * Previous focus: tools for screen display, e-commerce SI."
    )
    assert _looks_like_context_dump(dump)
    assert not _looks_like_context_dump("Board's clear, boss. 10:53 PM. Ready when you are.")
