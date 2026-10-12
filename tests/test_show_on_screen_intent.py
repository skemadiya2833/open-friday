"""Show/put on screen must route to computer_use, not chat hallucination."""

from __future__ import annotations

from friday.assistant import intent as I


def test_put_system_specs_on_screen_is_act():
    got = I._deterministic_intent("put my system specs on screen")
    assert got is not None
    assert got.mode == "act"
    assert got.skill_id == "computer_use"
    assert "show on screen" in got.reason


def test_bring_up_system_resources_is_act():
    got = I._deterministic_intent(
        "Can you bring up my resources that are on the system and put on screen"
    )
    assert got is not None
    assert got.mode == "act"
    assert got.skill_id == "computer_use"


def test_policy_does_not_veto_show_on_screen():
    raw = I.Intent(
        mode="act",
        skill_id="computer_use",
        confidence=0.9,
        objective="put my system specs on screen",
        reason="test",
        source="classifier",
    )
    got = I.apply_policy(raw, "put my system specs on screen")
    assert got.mode == "act"
    assert got.skill_id == "computer_use"
