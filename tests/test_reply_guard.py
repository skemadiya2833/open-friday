"""Shared anti-dump / relevancy guard — every model must answer the ask."""

from __future__ import annotations

from friday.assistant.reply_guard import (
    OUTPUT_CONTRACT,
    looks_like_prompt_dump,
    sanitize_assistant_reply,
)
from friday.persona import system_prompt


def test_output_contract_on_chat_prompt():
    text = system_prompt("chat")
    assert "Output contract" in text
    assert "Identity" in OUTPUT_CONTRACT


def test_observe_stays_lean():
    text = system_prompt("observe")
    assert "Output contract" not in text
    assert "Identity" not in text or "Do not mention Identity" in text


def test_detects_identity_tone_dump():
    dump = (
        "Identity: Friday\n"
        "Tone: calm, precise, loyal\n"
        "The user is asking while providing an image."
    )
    assert looks_like_prompt_dump(dump)


def test_detects_previous_focus_dump():
    dump = (
        'Previous focus\n'
        'User: "what\'s going on"\n'
        "Context: Saturday\n"
        "Agenda: []"
    )
    assert looks_like_prompt_dump(dump)


def test_normal_reply_passes():
    ok = "Chrome is open on a docs tab, and Cursor is behind it."
    assert not looks_like_prompt_dump(ok)
    assert sanitize_assistant_reply(ok, fallback="nope") == ok


def test_sanitize_replaces_dump():
    dump = "Identity: Friday\nTone: calm\nDoctrine: act"
    assert sanitize_assistant_reply(dump, fallback="Try once more.") == "Try once more."
