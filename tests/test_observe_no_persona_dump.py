"""Screen look must describe pixels — never recite Identity/Tone."""

from __future__ import annotations

from friday.models.local import _looks_like_optics_dump
from friday.persona import system_prompt


def test_optics_dump_detected():
    dump = (
        'The user is asking "Can you see my screen" while providing an image of their '
        "desktop environment. * Identity: Friday (personal AI). * Tone: Calm, precise, loyal, a step ahead."
    )
    assert _looks_like_optics_dump(dump)
    assert not _looks_like_optics_dump(
        "Yes — Cursor is open on Open Friday, and a terminal is visible at the bottom."
    )


def test_observe_prompt_has_no_doctrine_ballast():
    text = system_prompt("observe_voice")
    assert "Honesty (non-negotiable)" not in text
    assert "Session continuity" not in text
    assert "Quiet background topics" not in text
    assert "screenshot" in text.lower() or "desktop" in text.lower()
