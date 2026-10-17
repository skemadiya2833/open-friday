"""Hardware status must be measured — never invent a 4090 in chat."""

from __future__ import annotations

from friday.assistant.intent import classify_intent
from friday.assistant.orchestrator import _fake_hardware_report, _recover_action_objective
from friday.agent.direct_tools import _SHOW_SPECS_ON_SCREEN


def test_hardware_status_routes_to_computer_use():
    for msg in (
        "Where's my current Hardware status",
        "check system hardware",
        "my system specs",
        "show my pc specs",
        "what is my hardware status",
    ):
        intent = classify_intent(msg)
        assert intent.skill_id == "computer_use", msg
        assert "hardware" in intent.reason or "screen" in intent.reason, (msg, intent.reason)


def test_specs_regex_matches_hardware_status():
    assert _SHOW_SPECS_ON_SCREEN.search("Where's my current Hardware status")
    assert _SHOW_SPECS_ON_SCREEN.search("check system hardware")


def test_fake_4090_report_detected():
    reply = (
        "Hardware summary: CPU: Intel Core i7-12700K @ 3.5 GHz (12 cores, 16 threads) "
        "RAM: 32 GB DDR4 @ 3200 MHz GPU: NVIDIA GeForce RTX 4090 — 16 GB VRAM. "
        "I ran systeminfo. No spoofing, no guesswork."
    )
    assert _fake_hardware_report(reply)
    obj, skill = _recover_action_objective("You sure?", [], reply)
    assert skill == "computer_use"
    assert "hardware" in obj.lower()
