"""Deterministic identity answers — never let the model dump callsign instructions."""

from __future__ import annotations

import re

_IDENTITY_ASK = re.compile(
    r"(?i)\b("
    r"who are you|what('?s| is) your name|"
    r"are you (friday|jarvis|ultron|vision|karen|edith|electron|an? ai)|"
    r"i thought you (were|are)|"
    r"you sure\b|"
    r"still (friday|jarvis|ultron|vision|karen|edith)|"
    r"you('?re| are) (friday|jarvis|ultron|vision|karen|edith|electron)|"
    r"what callsign|which (mode|persona|callsign)"
    r")"
)


def is_identity_ask(message: str) -> bool:
    return bool(_IDENTITY_ASK.search(message or ""))


def identity_answer(message: str, owner: str) -> str:
    """Spoken identity for the active callsign. Handles ASR 'electron' ≠ Electron app."""
    from friday.presence.registry import active_skin

    skin = active_skin()
    base = skin.identity_reply(owner)
    low = (message or "").lower()
    if "electron" in low and skin.id != "edith":
        return (
            f"Sure — I'm {skin.display_name}, {owner}. "
            "Not Electron the app framework. Local callsign on this PC."
        )
    if re.search(r"(?i)\bi thought you (were|are)\b", low) or re.search(
        r"(?i)\byou sure\b", low
    ):
        return f"Sure thing — {base}"
    return base
