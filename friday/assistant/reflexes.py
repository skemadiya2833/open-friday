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


def try_reflex(message: str) -> ReflexHit | None:
    msg = (message or "").strip()
    if not msg or len(msg) > 120:
        return None

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

    if re.match(
        r"^(hi|hello|hey|good (morning|afternoon|evening))[,!. ]*$",
        msg,
        re.I,
    ):
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
