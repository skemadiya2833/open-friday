"""Deterministic identity answers — only for clear who/name/callsign asks."""

from __future__ import annotations

import re

# Keep this tight. "You sure about that" is normal chat — never identity dump.
_IDENTITY_ASK = re.compile(
    r"(?i)\b("
    r"who are you|"
    r"what('?s| is) your name|"
    r"are you (friday|jarvis|ultron|vision|karen|edith|piegi|electron|an? ai)|"
    r"i thought you (were|are)\s+(friday|jarvis|ultron|vision|karen|edith|piegi|an? ai)|"
    r"still (friday|jarvis|ultron|vision|karen|edith|piegi)\b|"
    r"you('?re| are) (friday|jarvis|ultron|vision|karen|edith|piegi|electron)|"
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
    return base
