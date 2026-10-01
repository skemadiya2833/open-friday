"""Intent brain: deterministic + policy must veto dumb Act mistakes."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_look_question_never_acts():
    from friday.assistant.intent import Intent, apply_policy, classify_intent

    msg = "Can you see what is going on on my desktop"
    # Even if the model hallucinates Act…
    bad = Intent(
        mode="act",
        skill_id="computer_use",
        confidence=0.99,
        objective=msg,
        reason="hallucinated",
        source="classifier",
    )
    fixed = apply_policy(bad, msg)
    assert fixed.mode == "look"
    assert fixed.skill_id == "observe"
    assert fixed.source == "policy"

    # And the full classifier must not call Act either (deterministic path).
    intent = classify_intent(msg)
    assert intent.mode == "look"
    assert intent.skill_id == "observe"


def test_imperative_can_act():
    from friday.assistant.intent import classify_intent

    intent = classify_intent("Open notepad and type hello")
    assert intent.mode == "act"
    assert intent.skill_id == "computer_use"


def test_greeting_is_talk():
    from friday.assistant.intent import classify_intent

    intent = classify_intent("hello")
    assert intent.mode == "talk"
    assert intent.skill_id == "chat"


def test_act_without_imperative_vetoed():
    from friday.assistant.intent import Intent, apply_policy

    bad = Intent(
        mode="act",
        skill_id="computer_use",
        confidence=0.9,
        objective="maybe do something",
        reason="confused",
    )
    fixed = apply_policy(bad, "How's the weather today?")
    assert fixed.mode != "act"
    assert fixed.skill_id != "computer_use"


if __name__ == "__main__":
    test_look_question_never_acts()
    test_imperative_can_act()
    test_greeting_is_talk()
    test_act_without_imperative_vetoed()
    print("ok")
