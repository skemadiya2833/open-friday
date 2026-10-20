"""'What's going on' must not recite knowledge-graph / prompt scaffolding."""

from __future__ import annotations

from friday.assistant import intent as I
from friday.assistant.reflexes import _strip_address, try_reflex
from friday.assistant.reply_guard import looks_like_prompt_dump


def test_strip_address_okay_not_ok_prefix():
    # Regression: ``ok`` must not strip the first two letters of ``Okay``.
    assert _strip_address("Okay Friday what's going on") == "what's going on"
    assert _strip_address("Ok Friday what's up") == "what's up"


def test_whats_going_on_is_reflex(monkeypatch):
    monkeypatch.setattr(
        "friday.tasks.plan.get_plan",
        lambda: {"items": [{"text": "3D printing business — explore and plan", "done": False}]},
    )
    for msg in (
        "Hey Friday what's going on",
        "Okay Friday what's going on",
        "what's going on",
    ):
        hit = try_reflex(msg)
        assert hit is not None, msg
        assert hit.label == "situation", msg
        assert "previous focus" not in hit.reply.lower()
        assert "e-commerce" not in hit.reply.lower()
        assert "3D printing" in hit.reply or "agenda" in hit.reply.lower() or "Board" in hit.reply


def test_okay_friday_situation_not_computer_use():
    got = I._deterministic_intent("Okay Friday what's going on")
    assert got is not None
    assert got.skill_id == "chat"
    assert got.mode == "talk"
    assert "situation" in got.reason


def test_context_dump_detected():
    dump = (
        '* User: "Hey Friday what\'s going on" * Context: Saturday, Oct 17, 2026, 10:53 PM. '
        "* Agenda: [ ] 3D printing. * Previous focus: tools for screen display, e-commerce SI."
    )
    assert looks_like_prompt_dump(dump)
    assert not looks_like_prompt_dump("Board's clear, boss. 10:53 PM. Ready when you are.")
