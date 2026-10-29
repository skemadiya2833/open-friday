"""Screen look must be deterministic observe — no chat token burn."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_screen_look_phrases_are_deterministic_observe():
    from friday.assistant.intent import (
        _deterministic_intent,
        is_camera_look_utterance,
        is_screen_look_utterance,
    )

    phrases = [
        "can you see my screen",
        "Can you see my screen?",
        "are you able to see my screen",
        "see my screen",
        "uh can you see my screen",
        "um Friday can you see my screen",
        "what's on my screen",
        "look at my screen",
        "describe the desktop",
        "take a screenshot",
        "can you see the screen",
    ]
    for msg in phrases:
        assert is_screen_look_utterance(msg), msg
        assert not is_camera_look_utterance(msg), msg
        hit = _deterministic_intent(msg)
        assert hit is not None, msg
        assert hit.mode == "look", msg
        assert hit.skill_id == "observe", msg
        assert hit.source == "policy", msg


def test_camera_not_stolen_by_screen_helper():
    from friday.assistant.intent import (
        _deterministic_intent,
        is_camera_look_utterance,
        is_screen_look_utterance,
    )

    for msg in ("can you see me", "look at me", "what's on my desk"):
        assert is_camera_look_utterance(msg), msg
        assert not is_screen_look_utterance(msg), msg
        hit = _deterministic_intent(msg)
        assert hit is not None and hit.skill_id == "camera", msg


def test_classify_screen_look_never_calls_llm(monkeypatch):
    from friday.assistant import intent as intent_mod

    called = {"n": 0}

    def _boom(*_a, **_k):
        called["n"] += 1
        raise AssertionError("LLM classify must not run for screen look")

    monkeypatch.setattr(intent_mod, "_llm_classify", _boom)
    intent = intent_mod.classify_intent("uh are you able to see my screen")
    assert intent.skill_id == "observe"
    assert intent.mode == "look"
    assert called["n"] == 0
