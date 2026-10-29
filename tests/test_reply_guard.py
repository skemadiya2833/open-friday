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
    assert "plain spoken" in OUTPUT_CONTRACT.lower()
    assert "never write analysis" in OUTPUT_CONTRACT.lower()
    assert OUTPUT_CONTRACT in text
    assert "I" in OUTPUT_CONTRACT and "you" in OUTPUT_CONTRACT
    # Chat must stay lean — labeled knowledge/doctrine blocks train dump formats.
    assert "Quiet background topics" not in text
    assert "Learned doctrine" not in text
    assert "Session continuity" not in text


def test_observe_stays_lean():
    text = system_prompt("observe")
    assert "Output contract" not in text
    assert "Truth rules" not in text
    assert "screenshot" in text.lower() or "desktop" in text.lower()


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
    assert (
        looks_like_prompt_dump("I am an AI assistant.") is False
    )  # plain claim — not label dump
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


def test_detects_analysis_outline_dump():
    dump = (
        "The user wants me to identify the main open application or window and describe "
        "its content from the provided image. 1. Identify the main application: "
        "The image shows a code editor, specifically VS Code."
    )
    assert looks_like_prompt_dump(dump)
    from friday.models.local import _looks_like_optics_dump

    assert _looks_like_optics_dump(dump)


def test_detects_boss_says_meta_dump():
    dump = (
        'The user (boss) says "See that again The free CID is opened in my desktop '
        'and I think the server should be". * "free CID" likely means FreeCAD. '
        '* "opened in my desktop" implies the application is running.'
    )
    assert looks_like_prompt_dump(dump)


def test_detects_thinking_process_dump():
    dump = (
        "Here's a thinking process that leads to the answer: 1. Analyze the Request: "
        "* Goal: Identify the frontmost app and what is visible in it."
    )
    assert looks_like_prompt_dump(dump)
    from friday.models.local import _looks_like_optics_dump

    assert _looks_like_optics_dump(dump)


def test_detects_day_outline_constraint_dump():
    dump = (
        "Here's today's outline. • * User Persona: Friday (an assistant). "
        "• * Output Constraint: ONLY a compact day outline as 4-6 bullet lines."
    )
    assert looks_like_prompt_dump(dump)


def test_detects_previous_focus_dump():
    dump = 'Previous focus\nUser: "what\'s going on"\nContext: Saturday\nAgenda: []'
    assert looks_like_prompt_dump(dump)


def test_normal_reply_passes():
    ok = "Chrome is open on a docs tab, and Cursor is behind it."
    assert not looks_like_prompt_dump(ok)
    assert sanitize_assistant_reply(ok, fallback="nope") == ok


def test_sanitize_replaces_dump():
    dump = "Identity: Friday\nTone: calm\nDoctrine: act"
    assert sanitize_assistant_reply(dump, fallback="Try once more.") == "Try once more."


def test_detects_persona_planning_dump():
    dump = (
        '* User wants me to switch my "callsign" or persona to "Quinn". '
        "* Previous interaction was a bit confused. "
        '* I need to adopt the "Quinn" persona while maintaining the core constraints: '
        "local assistant on Windows, calm/precise/warm, short sentences, no lists/markdown."
    )
    assert looks_like_prompt_dump(dump)
    assert (
        sanitize_assistant_reply(dump, fallback="Say that again?") == "Say that again?"
    )


def test_detects_callsign_instruction_leak():
    dump = (
        'The user is asking if I am "Friday" or if I have switched to "Ultron". '
        'The system instructions state: "Callsign Ultron: theatrical, dry megalomania '
        "as *jokes only* — ironic superiority, never real harm. Mock-threaten entropy "
        "and mediocrity, then still help."
    )
    assert looks_like_prompt_dump(dump)


def test_detects_identity_questioning_dump():
    dump = (
        'The user is questioning my identity ("You sure I thought you were electron"). '
        'I am "Friday", a local assistant on the Windows PC. "Electron" might be another persona.'
    )
    assert looks_like_prompt_dump(dump)
