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
    r"(?i)\buser'?s\s+goal\s*:",
    r"(?i)\bconstraint\s*\d+\s*:",
    r"(?i)\b\*+\s*correction\s*\*+",
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
    r"(?i)\bthe user is asking if\b",
    r"(?i)\bthe user is questioning\b",
    r"(?i)\bthe user is challenging\b",
    r"(?i)\bdidn'?t automatically capture\b",
    r"(?i)\bbecause i didn'?t\b",
    r"(?i)\*\s*friday\s*:\s*calm",
    r"(?i)\bcalm,\s*precise,\s*a step ahead\b",
    r"(?i)\bmain app open\s*:",
    r"(?i)\bvisible apps?\s*:",
    r"(?i)\bcompetence over commentary\b",
    r"(?i)\bcoffee optional;\s*competence\b",
    # Fake tool/status theater — observe already ran; never narrate wiring.
    r"(?i)\bdesktop vision agent\b",
    r"(?i)\bvision agent\b",
    r"(?i)\bvision/?desktop\b",
    r"(?i)\bvision tool\b",
    r"(?i)\btool wired up\b",
    r"(?i)\b(didn'?t|did not) run this turn\b",
    r"(?i)\btrigger(?:ed)? the (?:desktop )?vision\b",
    r"(?i)\bcan'?t see your screen\b",
    r"(?i)\bcannot see your screen\b",
    r"(?i)\bin this chat channel\b",
    r"(?i)\bquestioning my identity\b",
    r"(?i)\bmight be another persona\b",
    r"(?i)\bthe user wants me to\b",
    r"(?i)\bthe user wants to know\b",
    r"(?i)\bthe user said\b",
    r"(?i)\bin response to my previous\b",
    r"(?i)\blooking back at the conversation\b",
    r"(?i)\buser wants me to\b",
    r"(?i)\bin the webcam image provided\b",
    r"(?i)\banalyze the image\b",
    r"(?i)\bi need to adopt\b",
    r"(?i)\badopt the .{0,40}persona\b",
    r"(?i)\bmaintaining the core constraints\b",
    r"(?i)\bcore constraints\b",
    r"(?i)\bprevious interaction was\b",
    r"(?i)\bthe system instructions?\b",
    r"(?i)\bsystem instructions? state\b",
    r"(?i)\bcallsign ultron:\b",
    r"(?i)\btheatrical, dry megalomania\b",
    r"(?i)\bas \*jokes only\*\b",
    r"(?i)\bmock-threaten entropy\b",
    r"(?i)\bthe user\s*\(\s*boss\s*\)\s*says\b",
    r"(?i)\bthe user\s*\(\s*boss\s*\)\b",
    r"(?i)\blikely means\b",
    r"(?i)\bimplies (the |that )?(application|app|process|server)\b",
    r"(?i)\bhere'?s a thinking process\b",
    r"(?i)\bthinking process that leads\b",
    r"(?i)\banalyze the request\b",
    r"(?i)\buser\s*persona\s*:",
    r"(?i)\boutput\s*constraint\s*:",
    r"(?i)\boutput\s*only\s*a\s+compact\s+day\s+outline\b",
    r"(?i)\b4-6\s+bullet\s+lines\b",
    r"(?i)\bwhile providing an image\b",
    r"(?i)\bfrom the provided image\b",
    r"(?i)\bidentify the main (application|open)\b",
    r"(?i)\bthe image shows\b",
    r"(?i)\bpersonal ai\)",
    r"(?i)\bcalm,\s*precise,\s*loyal\b",
    r"(?i)\bcalm[/,]\s*precise[/,]\s*warm\b",
    r"(?i)\bdry wit allowed\b",
    r"(?i)\bsystem prompt\b",
    r"(?i)\ban ai assistant\b",
    r"(?i)\b1-2 short sentences\b",
    r"(?i)\bno lists/?markdown\b",
    r"(?i)\bthe prompt says\b",
    r"(?i)\btell the user you could not reach search\b",
    # Vision caption theater — models label the frame instead of answering.
    r"(?i)^\s*image\s*:",
    r"(?i)\ba screenshot of (a |the )?(windows )?desktop\b",
    r"(?i)\blikely running (a )?linux\b",
    r"(?i)\busing wsl/docker\b",
    # Numbered analysis outline instead of a spoken answer.
    r"(?i)^\s*1\.\s*identify\b",
    r"(?i)^\s*1\.\s*analyze\b",
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
    # Strong single-hit theater — never wait for a second pattern.
    if re.search(
        r"(?i)\b("
        r"the user\s*\(\s*boss\s*\)\s*says|"
        r"here'?s a thinking process|"
        r"thinking process that leads|"
        r"analyze the request|"
        r"user\s*persona\s*:|"
        r"output\s*constraint\s*:|"
        r"maintaining the core constraints|"
        r"i need to adopt|"
        r"adopt the .{0,40}persona|"
        r"the system instructions?|"
        r"system instructions? state|"
        r"the user is asking if|"
        r"the user is questioning|"
        r"questioning my identity|"
        r"theatrical, dry megalomania|"
        r"mock-threaten entropy|"
        r"competence over commentary|"
        r"desktop vision agent|"
        r"vision agent|"
        r"vision tool|"
        r"tool wired up|"
        r"(?:didn'?t|did not) run this turn|"
        r"trigger(?:ed)? the (?:desktop )?vision|"
        r"can'?t see your screen|"
        r"cannot see your screen|"
        r"in this chat channel"
        r")\b",
        t,
    ):
        return True
    hits = sum(1 for pat in _DUMP_PATTERNS if re.search(pat, t))
    if hits >= 2:
        return True
    if hits >= 1 and re.search(
        r"(?i)\b("
        r"agenda|previous focus|context:|identity|tone|doctrine|role\s*:|"
        r"persona\s*:|constraints?\s*:|user'?s\s+input|"
        r"the user wants|user wants me|the user\s*\(\s*boss\s*\)|likely means|"
        r"identify the main|from the provided image|the image shows|"
        r"callsign|core constraints|no lists"
        r")\b",
        t,
    ):
        return True
    # Analysis outline: "The user wants me to… 1. Identify…"
    if re.search(r"(?i)\b(the )?user wants me to\b", t) and re.search(
        r"(?i)^\s*\d+\.\s+\w+|^\s*\*\s+", t, re.MULTILINE
    ):
        return True
    # Bullet planning dump: "* User wants… * Previous… * I need to adopt…"
    if t.count("*") >= 2 and re.search(
        r"(?i)\b(user wants me|previous interaction|core constraints|adopt .{0,20}persona)\b",
        t,
    ):
        return True
    return False


# Chat / talk turns with no tools must not invent PC side effects.
_FAKE_SIDE_EFFECT = re.compile(
    r"(?i)\b("
    r"i('?ve| have)?\s+(just\s+)?(created|saved|exported|written|wrote|put|placed|dropped|built|made)\b.{0,80}\b"
    r"(on (your|the|my) desktop|to (your|the|my) desktop|as .*\.fcstd|\.fcstd|freecad|"
    r"cad (file|part)|3\s*-?\s*d\s*(model|file)|desktop)"
    r"|"
    r"(file|model|part|\.fcstd|fcstd)\b.{0,40}\b(is|are|was|were)\b.{0,40}\b"
    r"(on (your|the) desktop|ready on (your|the) desktop|saved)"
    r"|"
    r"(opened|launched|started)\b.{0,40}\bfreecad\b.{0,40}\b(and|&)\b.{0,40}\b(built|created|saved)"
    r")",
)


def claims_unbacked_pc_action(reply: str) -> bool:
    """True if the reply asserts a file/CAD/desktop action that needs a real tool."""
    return bool(_FAKE_SIDE_EFFECT.search(reply or ""))


def sanitize_assistant_reply(reply: str, *, fallback: str) -> str:
    text = (reply or "").strip()
    if not text or looks_like_prompt_dump(text):
        return (fallback or "").strip()
    return text
