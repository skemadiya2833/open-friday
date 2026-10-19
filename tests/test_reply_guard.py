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


def test_detects_role_solo_dump():
    assert looks_like_prompt_dump("• Role: Friday (an AI assistant).")
    assert looks_like_prompt_dump("Role: Friday (an AI assistant).")
    assert looks_like_prompt_dump("I am an AI assistant.") is False  # plain claim — not label dump
    assert looks_like_prompt_dump("Role: Friday\nTone: calm")


def test_detects_meta_analysis_dump():
    dump = (
        '* User\'s input: "Uh my monitors are placed…" * Context: The user is describing '
        "their physical workspace setup * Persona: Friday (calm, precise, loyal, generous, "
        "dry wit allowed). * Constraints: 1-2 short sentences. No…"
    )
    assert looks_like_prompt_dump(dump)


def test_detects_image_caption_dump():
    dump = (
        "Image: A screenshot of a Windows desktop (likely running a Linux environment "
        "or using WSL/Docker given the terminal content)."
    )
    assert looks_like_prompt_dump(dump)
    from friday.models.local import _looks_like_optics_dump

    assert _looks_like_optics_dump(dump)
    assert not _looks_like_optics_dump(
        "Cursor is open on cli.py, and a PowerShell window is behind it."
    )


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
