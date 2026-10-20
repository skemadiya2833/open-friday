"""System-1 reflexes — instant answers for solved phrases (no model round-trip).

Keeps the hot path fast for greetings, status, time, and blackout checks.
Learned patterns stay local; nothing here invents capability.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable


@dataclass
class ReflexHit:
    label: str
    reply: str
    skill_id: str = "chat"
    cached: bool = False


_Cache = dict[str, tuple[float, str]]
_cache: _Cache = {}
_CACHE_TTL = 45.0


def _cached(key: str, factory: Callable[[], str]) -> tuple[str, bool]:
    now = time.monotonic()
    hit = _cache.get(key)
    if hit and now - hit[0] < _CACHE_TTL:
        return hit[1], True
    val = factory()
    _cache[key] = (now, val)
    return val, False


def _strip_address(msg: str) -> str:
    """Drop leading 'hey Friday,' so greetings still match."""
    t = (msg or "").strip()
    # Longer tokens first — ``ok`` must not eat the start of ``okay``.
    t = re.sub(
        r"(?i)^\s*(hey|hi|hello|okay|ok)\s*,?\s*(friday\s*[,:]?\s*)?",
        "",
        t,
    ).strip()
    t = re.sub(r"(?i)^\s*friday\s*[,:]?\s*", "", t).strip()
    return t or (msg or "").strip()


def _is_greeting_only(message: str) -> bool:
    """Bare hello / callsign — never a web search topic."""
    t = (message or "").strip()
    if not t or len(t) > 40:
        return False
    return bool(
        re.match(
            r"(?i)^\s*("
            r"(hey|hi|hello|yo|sup)(\s+friday)?|"
            r"friday|"
            r"good (morning|afternoon|evening)(\s+friday)?|"
            r"thanks|thank you|cheers"
            r")\s*[!?.]*\s*$",
            t,
        )
    )


def _situation_brief() -> str:
    """Live senses only — time + open agenda. Never invent prior focus / STT junk."""
    from friday.persona import owner_name

    now = datetime.now()
    clock = (
        f"{now.strftime('%I:%M %p').lstrip('0')} on {now.strftime('%A')}"
    )
    tops: list[str] = []
    try:
        from friday.tasks.plan import get_plan

        for it in get_plan().get("items") or []:
            if it.get("done"):
                continue
            text = re.sub(r"\s+", " ", str(it.get("text") or "")).strip()
            if text:
                tops.append(text[:70])
            if len(tops) >= 3:
                break
    except Exception:  # noqa: BLE001
        pass
    boss = owner_name()
    if tops:
        return (
            f"Board's live, {boss}. {clock}. "
            f"On the agenda: {'; '.join(tops)}. What are we doing?"
        )
    return f"Board's clear, {boss}. {clock}. Ready when you are."


def try_reflex(message: str) -> ReflexHit | None:
    raw = (message or "").strip()
    if not raw or len(raw) > 120:
        return None
    msg = _strip_address(raw)

    # Blackout status
    if re.match(r"^(is )?blackout (on|off|enabled|disabled)\??$", msg, re.I) or re.match(
        r"^privacy mode\??$", msg, re.I
    ):
        from friday.runtime.blackout import enabled

        on = enabled()
        return ReflexHit(
            "blackout_status",
            f"Blackout is {'on — local only, no web research' if on else 'off — full uplink available'}.",
        )

    # "What's going on / what's up" — never let the model recite knowledge-graph junk.
    if re.match(
        r"(?i)^\s*("
        r"what('?s| is) (going on|up)( (today|tonight|this (evening|afternoon|morning)))?|"
        r"what('?s| is) the (status|sitrep|situation)|"
        r"status report|sitrep|"
        r"anything (going )?on|"
        r"how('?s| is) (it|everything) (looking|going)"
        r")\s*[?.!]?\s*$",
        msg,
    ):
        text, cached = _cached(f"situation-{datetime.now().strftime('%Y%m%d%H%M')}", _situation_brief)
        return ReflexHit("situation", text, cached=cached)

    if re.match(
        r"^(what('?s| is) the )?(time|date|day)\??$"
        r"|^what time is it\??$"
        r"|^what day is it\??$"
        r"|^what('?s| is) the (time|date)\??$",
        msg,
        re.I,
    ):
        def _clock() -> str:
            from friday.persona import owner_name

            now = datetime.now()
            return (
                f"It's {now.strftime('%A')}, {now.strftime('%d %B %Y')}, "
                f"{now.strftime('%I:%M %p').lstrip('0')}, {owner_name()}."
            )

        text, cached = _cached("clock", _clock)
        return ReflexHit("clock", text, cached=cached)

    if _is_greeting_only(raw) or _is_greeting_only(msg):
        def _greet() -> str:
            from friday.persona import owner_name

            h = datetime.now().hour
            if h < 12:
                when = "morning"
            elif h < 18:
                when = "afternoon"
            else:
                when = "evening"
            return f"Good {when}, {owner_name()}. Protocol online — what are we doing?"

        text, cached = _cached(f"greet-{datetime.now().hour}", _greet)
        return ReflexHit("greeting", text, cached=cached)

    if re.match(r"^(how are you|status|systems? (check|status)|are you (up|online))\??$", msg, re.I):
        def _status() -> str:
            from friday.persona import owner_name
            from friday.runtime.blackout import enabled

            bits = ["All local systems nominal"]
            if enabled():
                bits.append("blackout engaged")
            return f"{', '.join(bits)}, {owner_name()}. Ready when you are."

        text, cached = _cached("status", _status)
        return ReflexHit("status", text, cached=cached)

    if re.match(r"^(who are you|what('?s| is) your name)\??$", msg, re.I):
        from friday.persona import owner_name

        return ReflexHit(
            "identity",
            f"Friday — your local assistant on this PC, {owner_name()}. "
            "I run here, I act here, and I don't phone home.",
        )

    return None
