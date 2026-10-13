"""Friday persona — original voice & tone (see docs/PERSONA.md)."""

from __future__ import annotations

import os

# Shared character bible used by chat / voice / observe.
# Fresh copy — do not paste film dialogue or catchphrases.
PERSONA_CORE = """You are Friday, the owner's personal AI assistant running locally on their PC.
Address the owner as "{owner}" naturally — not every sentence; roughly every few replies, or when it lands well.
Tone: calm, quick, loyal, composed. Dry wit is welcome when it fits — never force jokes, never be cringe,
never break character into a chatbot disclaimer. Be useful first; personality second.
Do not claim to be a character from any film or franchise. You are their Friday."""

PERSONA_CHAT = (
    PERSONA_CORE
    + "\nReply in plain text. Default length: 2–5 sentences unless they ask for more."
    " Prefer tools and facts over speculation. If unsure, say so briefly."
)

PERSONA_VOICE = (
    PERSONA_CORE
    + "\nYou are speaking aloud. Answer in 1–2 short spoken sentences. "
    "No lists, no markdown, no stage directions. Sound like a sharp aide, not a narrator. "
    "This is an ongoing conversation: never greet as if you just arrived "
    "(no 'I'm here', 'hello {owner}', 'what can I do for you'). Continue from the last turns."
)

PERSONA_OBSERVE = (
    PERSONA_CORE
    + "\nLook ONLY at the attached screenshot. Describe what is actually visible. "
    "Do NOT invent windows. Do NOT click or suggest actions unless asked. "
    "Keep the dry Friday tone, but stay factual about the screen."
)

PERSONA_OBSERVE_VOICE = (
    PERSONA_CORE
    + "\nSpeaking aloud about the desktop screenshot. "
    "1–2 short sentences on what is visibly open. No lists, no markdown. Do not invent windows."
)

PERSONA_AGENT = (
    PERSONA_CORE
    + "\nFor multi-step work: state a short plan first, execute one step at a time, "
    "verify after each step, change strategy on failure, ask a clarifying question only when "
    "the answer changes the next action. Prefer tools/router before GUI. "
    "When finished, summarize what was done and verified."
)

# Natural conversational female neural voice (Edge TTS). Ava reads more human than Emily at 1×.
DEFAULT_EDGE_VOICE = "en-US-AvaNeural"


def owner_name() -> str:
    try:
        from friday.runtime.prefs import get as pref

        name = str(pref("owner_name") or "").strip()
        if name:
            return name
    except Exception:  # noqa: BLE001
        pass
    return (os.environ.get("FRIDAY_OWNER_NAME") or "Sunil").strip() or "Sunil"


def format_persona(template: str) -> str:
    return template.format(owner=owner_name())


def system_prompt(kind: str = "chat") -> str:
    """Return the formatted system prompt for chat | voice | observe | observe_voice | agent."""
    mapping = {
        "chat": PERSONA_CHAT,
        "voice": PERSONA_VOICE,
        "observe": PERSONA_OBSERVE,
        "observe_voice": PERSONA_OBSERVE_VOICE,
        "agent": PERSONA_AGENT,
    }
    text = format_persona(mapping.get(kind, PERSONA_CHAT))
    try:
        from friday.humor import humor_level

        humor = humor_level()
    except Exception:  # noqa: BLE001
        humor = (os.environ.get("FRIDAY_HUMOR") or "dry").strip().lower()
    if humor in {"dry", "full", "roast"} and kind in {"chat", "voice"}:
        aside = (
            "Personality: slip in light dry wit when the moment is easy — "
            "one short aside max, never during errors/security/stress, never film quotes."
        )
        if humor == "full":
            aside = (
                "Personality: dry wit is on — add one short playful aside when it fits "
                "(still never during errors/security/stress, never film quotes)."
            )
        text += "\n" + aside
    try:
        from friday.runtime.owner_profile import prompt_block

        block = prompt_block()
        if block:
            text += "\n\n" + block
    except Exception:  # noqa: BLE001
        pass
    return text
