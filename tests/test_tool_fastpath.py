"""Clear tool asks must skip chat tokens — intent → skill directly."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_memory_beats_cad_keyword():
    from friday.assistant.intent import _deterministic_intent, match_tool_fastpath

    msg = "what do you remember about freecad"
    fast = match_tool_fastpath(msg)
    assert fast is not None and fast.skill_id == "memory"
    hit = _deterministic_intent(msg)
    assert hit is not None and hit.skill_id == "memory"


def test_memory_store_and_recall_phrases():
    from friday.assistant.intent import match_tool_fastpath

    for msg in (
        "remember that my name is Sunil",
        "do you remember my wifi password tip",
        "search your memory for robot",
        "uh what do you know about me",
        "check your notes for ESP",
    ):
        hit = match_tool_fastpath(msg)
        assert hit is not None, msg
        assert hit.skill_id == "memory", msg


def test_remember_to_is_tasks_not_memory():
    from friday.assistant.intent import is_memory_utterance, match_tool_fastpath

    msg = "remember to stand up in 20 minutes"
    assert not is_memory_utterance(msg)
    hit = match_tool_fastpath(msg)
    assert hit is not None and hit.skill_id == "tasks"


def test_tasks_and_camera_fastpath():
    from friday.assistant.intent import match_tool_fastpath

    for msg, skill in (
        ("remind me in 10 minutes to stand", "tasks"),
        ("whats on my agenda today", "tasks"),
        ("add buy milk to my plan", "tasks"),
        ("can you see me", "camera"),
        ("look through the webcam", "camera"),
        ("look at me", "camera"),
        ("can you see my screen", "observe"),
    ):
        hit = match_tool_fastpath(msg)
        assert hit is not None, msg
        assert hit.skill_id == skill, (msg, hit.skill_id)


def test_classify_tool_fastpath_skips_llm(monkeypatch):
    from friday.assistant import intent as intent_mod

    def _boom(*_a, **_k):
        raise AssertionError("LLM classify must not run for tool fastpath")

    monkeypatch.setattr(intent_mod, "_llm_classify", _boom)
    for msg in (
        "remember that the gate code is 42",
        "do you remember the gate code",
        "look through the webcam",
        "whats on schedule today",
    ):
        intent = intent_mod.classify_intent(msg)
        assert intent.skill_id in {"memory", "camera", "tasks", "observe"}
        assert intent.source == "policy"


def test_pushback_retries_prior_camera_look():
    from friday.assistant.intent import classify_intent

    history = [
        {"role": "user", "content": "can you see me"},
        {
            "role": "assistant",
            "content": "I'm with you, boss. What do you need?",
        },
    ]
    intent = classify_intent(
        "You should be smart enough to do that already",
        history=history,
    )
    assert intent.mode == "look"
    assert intent.skill_id == "camera"


def test_pushback_retries_prior_screen_look():
    from friday.assistant.intent import classify_intent
    from friday.assistant.reply_guard import looks_like_prompt_dump

    dump = (
        "The user is challenging Friday's intelligence because I didn't "
        "automatically capture the screenshot. * Friday: Calm, precise, a step ahead."
    )
    assert looks_like_prompt_dump(dump)

    history = [
        {"role": "user", "content": "can you see my screen"},
        {"role": "assistant", "content": dump},
    ]
    intent = classify_intent("just do it already", history=history)
    assert intent.mode == "look"
    assert intent.skill_id == "observe"


def test_by_yourself_is_not_a_web_topic():
    from friday.assistant.intent import classify_intent

    hist = [
        {
            "role": "assistant",
            "content": "What should I search for — give me a topic or question.",
        }
    ]
    for msg in ("by yourself", "do it by yourself", "figure it out yourself"):
        intent = classify_intent(msg, history=hist)
        assert intent.skill_id != "research", (msg, intent.reason)
        assert intent.mode in {"talk", "clarify", "look"}, (msg, intent.mode)


def test_by_yourself_after_look_retries_camera():
    from friday.assistant.intent import classify_intent

    history = [
        {"role": "user", "content": "can you see me"},
        {"role": "assistant", "content": "I'm with you, boss. What do you need?"},
        {
            "role": "assistant",
            "content": "What should I search for — give me a topic or question.",
        },
    ]
    # Prefer look retry over inventing a web topic from pushback ASR.
    intent = classify_intent("by yourself", history=history)
    assert intent.skill_id == "camera"
    assert intent.mode == "look"
