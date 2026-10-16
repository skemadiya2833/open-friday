"""Confirmations must act; learn-from-articles writes doctrine."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from friday.assistant.intent import classify_intent
from friday.runtime import doctrine as DOC


def test_yes_do_that_routes_to_prior_research():
    history = [
        {"role": "user", "content": "bring up some website references for 3d printing"},
        {
            "role": "assistant",
            "content": "Shall I open reference sites for 3D printing businesses?",
        },
    ]
    intent = classify_intent("Yes do that", history=history)
    assert intent.skill_id == "research"
    assert "3d printing" in intent.objective.lower() or "reference" in intent.objective.lower()


def test_learn_how_routes_research():
    intent = classify_intent("read articles on how to become a good assistant and learn them")
    assert intent.skill_id == "research"
    assert intent.mode == "research"
    assert "learn" in intent.reason or "learn" in intent.objective.lower()


def test_doctrine_stores_and_prompts(tmp_path, monkeypatch):
    monkeypatch.setattr("friday.config.DATA_DIR", Path(tmp_path))
    rec = DOC.add_lessons(
        "good assistant",
        [
            "Prefer action over promising.",
            "Confirm before risky clicks.",
            "Use tools instead of narrating.",
        ],
        sources=["https://example.com/a"],
    )
    assert len(rec["bullets"]) == 3
    block = DOC.prompt_block()
    assert "Prefer action" in block
    assert "Learned doctrine" in block


def test_fake_promise_detects_opening_browser():
    from friday.assistant.orchestrator import _fake_action_promise

    assert _fake_action_promise(
        "Opening a browser to load 3D printing reference sites now. Done.",
        "Yes do that",
    )


def test_false_capability_denial_detects_cloud_theater():
    from friday.assistant.orchestrator import _false_capability_denial

    assert _false_capability_denial(
        "I can't browse external websites or read documents in real-time, "
        "but I have access to my internal knowledge base on business productivity."
    )
    assert not _false_capability_denial("Opened three reference tabs for 3D printing.")
