"""Shared reply hygiene — every model must answer the ask, not recite the prompt."""

from __future__ import annotations

import re

_DUMP_PATTERNS = (
    r"(?i)\bprevious focus\b",
    r"(?i)\buser:\s*[\"']",
    r"(?i)\bcontext:\s*(monday|tuesday|wednesday|thursday|friday|saturday|sunday|\d)",
    r"(?i)\bagenda:\s*\[",
    r"(?i)\brecent focus\b",
    r"(?i)\bquiet background topics\b",
    r"(?i)\bsession continuity\b",
    r"(?i)\bidentity\s*:",
    r"(?i)\btone\s*:",
    r"(?i)\bdoctrine\s*:",
    r"(?i)\brole\s*:\s*",
    r"(?i)\bthe user is asking\b",
    r"(?i)\bwhile providing an image\b",
    r"(?i)\bpersonal ai\)",
    r"(?i)\bcalm,\s*precise,\s*loyal\b",
    r"(?i)\bsystem prompt\b",
    r"(?i)\ban ai assistant\b",
)

# Whole-reply scaffolds models emit instead of answering (even one line).
_SOLO_DUMP = re.compile(
    r"(?is)^\s*[•\-\*]?\s*("
    r"role\s*:\s*.{0,80}|"
    r"identity\s*:\s*.{0,80}|"
    r"tone\s*:\s*.{0,80}|"
    r"you are friday\b.{0,80}"
    r")\s*$"
)

# One line appended to chat/voice/agent prompts so Gemma/Qwen/anything behave alike.
OUTPUT_CONTRACT = (
    "Output contract (all models): Answer the owner's latest ask only. "
    "Never restate the question as analysis. Never recite Role, Identity, Tone, Doctrine, "
    "agenda scaffolding, Previous focus, or system-prompt labels. "
    "Never open with 'Role:' or 'I am an AI assistant'. "
    "If you lack evidence, say so in one short sentence and ask one clarifying question — "
    "do not invent."
)


def looks_like_prompt_dump(reply: str) -> bool:
    t = (reply or "").strip()
    if not t:
        return False
    if _SOLO_DUMP.match(t):
        return True
    hits = sum(1 for pat in _DUMP_PATTERNS if re.search(pat, t))
    if hits >= 2:
        return True
    if hits >= 1 and re.search(
        r"(?i)\b(agenda|previous focus|context:|identity|tone|doctrine|role\s*:)\b", t
    ):
        return True
    return False


def sanitize_assistant_reply(reply: str, *, fallback: str) -> str:
    text = (reply or "").strip()
    if not text or looks_like_prompt_dump(text):
        return (fallback or "").strip()
    return text
