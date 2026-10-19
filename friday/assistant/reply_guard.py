"""Shared reply hygiene — every model must answer the ask, not recite the prompt.

Prompt text (OUTPUT_CONTRACT) lives in ``friday.prompts``; this module only detects dumps.
"""

from __future__ import annotations

import re

from friday.prompts import OUTPUT_CONTRACT  # noqa: F401 — re-export for callers/tests

_DUMP_PATTERNS = (
    r"(?i)\bprevious focus\b",
    r"(?i)\buser:\s*[\"']",
    r"(?i)\buser'?s\s+input\s*:",
    r"(?i)\bcontext:\s*",
    r"(?i)\bpersona\s*:",
    r"(?i)\bconstraints?\s*:",
    r"(?i)\bagenda:\s*\[",
    r"(?i)\brecent focus\b",
    r"(?i)\bquiet background topics\b",
    r"(?i)\bsession continuity\b",
    r"(?i)\bidentity\s*:",
    r"(?i)\btone\s*:",
    r"(?i)\bdoctrine\s*:",
    r"(?i)\brole\s*:\s*",
    r"(?i)\bthe user is (asking|describing)\b",
    r"(?i)\bthe user wants me to\b",
    r"(?i)\bwhile providing an image\b",
    r"(?i)\bfrom the provided image\b",
    r"(?i)\bidentify the main (application|open)\b",
    r"(?i)\bthe image shows\b",
    r"(?i)\bpersonal ai\)",
    r"(?i)\bcalm,\s*precise,\s*loyal\b",
    r"(?i)\bdry wit allowed\b",
    r"(?i)\bsystem prompt\b",
    r"(?i)\ban ai assistant\b",
    r"(?i)\b1-2 short sentences\b",
    # Vision caption theater — models label the frame instead of answering.
    r"(?i)^\s*image\s*:",
    r"(?i)\ba screenshot of (a |the )?(windows )?desktop\b",
    r"(?i)\blikely running (a )?linux\b",
    r"(?i)\busing wsl/docker\b",
    # Numbered analysis outline instead of a spoken answer.
    r"(?i)^\s*1\.\s*identify\b",
)

# Whole-reply scaffolds models emit instead of answering (even one line).
_SOLO_DUMP = re.compile(
    r"(?is)^\s*[•\-\*]?\s*("
    r"role\s*:\s*.{0,120}|"
    r"identity\s*:\s*.{0,120}|"
    r"tone\s*:\s*.{0,120}|"
    r"persona\s*:\s*.{0,120}|"
    r"image\s*:\s*.{0,200}|"
    r"you are friday\b.{0,120}"
    r")\s*$"
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
        r"(?i)\b("
        r"agenda|previous focus|context:|identity|tone|doctrine|role\s*:|"
        r"persona\s*:|constraints?\s*:|user'?s\s+input|"
        r"the user wants|identify the main|from the provided image|the image shows"
        r")\b",
        t,
    ):
        return True
    # Analysis outline: "The user wants me to… 1. Identify…"
    if re.search(r"(?i)\bthe user wants me to\b", t) and re.search(
        r"(?i)^\s*\d+\.\s+\w+", t, re.M
    ):
        return True
    return False


def sanitize_assistant_reply(reply: str, *, fallback: str) -> str:
    text = (reply or "").strip()
    if not text or looks_like_prompt_dump(text):
        return (fallback or "").strip()
    return text
