"""Bare 'Hey Friday' is a greeting — never a Wikipedia quick-research dump."""

from __future__ import annotations

from friday.assistant.intent import classify_intent
from friday.assistant.reflexes import _is_greeting_only, try_reflex
from friday.skills.builtin.research.handler import SkillHandler


def test_hey_friday_is_greeting_only():
    for msg in ("Hey Friday", "hey friday", "Hi Friday!", "Friday", "Hello Friday"):
        assert _is_greeting_only(msg), msg
        hit = try_reflex(msg)
        assert hit is not None, msg
        assert hit.label == "greeting", msg
        assert "wikipedia" not in hit.reply.lower()
        assert "painting" not in hit.reply.lower()


def test_hey_friday_intent_is_chat():
    intent = classify_intent("Hey Friday")
    assert intent.skill_id == "chat"
    assert intent.mode == "talk"


def test_research_skill_refuses_greeting():
    h = SkillHandler()

    class Ctx:
        message = "Hey Friday"
        history = []
        voice_mode = True
        emit = staticmethod(lambda *a, **k: None)
        metadata = {}

    out = h.run(Ctx())  # type: ignore[arg-type]
    assert out.skill_id == "chat"
    assert "Holy Friday" not in (out.reply or "")
    assert "painting" not in (out.reply or "").lower()
