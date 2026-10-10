"""Humor policy: at most one short quip; never during errors/security/stress."""

from __future__ import annotations

import os
import re
import time
from collections import deque
from contextvars import ContextVar
from typing import Deque

# Per-request override from the Control Center Settings page.
_humor_override: ContextVar[str | None] = ContextVar("friday_humor_override", default=None)

# Hand-written originals only — no film quotes.
_BANK = [
    "Noted, and filed under 'things that will try us again later'.",
    "Consider it handled — with the usual quiet competence.",
    "Done. I'll pretend that was the easy part.",
    "On it. Try not to look too impressed.",
    "Sorted. Coffee optional; competence mandatory.",
    "That's the ticket. Moving on before it gets ideas.",
    "Finished. The universe remains unimpressed, as usual.",
    "All set. I'll keep the victory lap to a walk.",
]

_recent: Deque[str] = deque(maxlen=20)
_STRESS = re.compile(
    r"\b(urgent|emergency|asap|angry|upset|furious|crisis|panic|help me now|"
    r"something.?s wrong|broken|disaster)\b",
    re.I,
)
_ERR_MARKERS = re.compile(
    r"\b(error|failed|failure|denied|blocked|unauthorized|approval required|"
    r"couldn.?t|cannot|unable)\b",
    re.I,
)


def set_humor_override(level: str | None):
    """Context-local override (e.g. from chat request). Pass None to clear."""
    if level is None:
        _humor_override.set(None)
        return
    v = level.strip().lower()
    _humor_override.set(v if v in {"off", "dry", "full"} else None)


def humor_level() -> str:
    ov = _humor_override.get()
    if ov in {"off", "dry", "full"}:
        return ov
    v = (os.environ.get("FRIDAY_HUMOR") or "dry").strip().lower()
    return v if v in {"off", "dry", "full"} else "dry"


def should_quip(*, user_text: str = "", reply: str = "", is_error: bool = False,
                is_security: bool = False) -> bool:
    if humor_level() == "off":
        return False
    if is_error or is_security:
        return False
    if _STRESS.search(user_text or ""):
        return False
    if _ERR_MARKERS.search(reply or ""):
        return False
    return True


def _rubric_ok(line: str) -> bool:
    s = (line or "").strip()
    if not s or len(s) > 120:
        return False
    if s in _recent:
        return False
    # Block obvious film-quote patterns / trademark bait
    banned = ("i am iron", "assemble", "jarvis", "stark industries", "suit up")
    low = s.lower()
    if any(b in low for b in banned):
        return False
    return True


def pick_fallback_quip(*, context: str = "") -> str | None:
    if humor_level() == "off":
        return None
    hour = time.localtime().tm_hour
    timed = None
    if 5 <= hour < 12:
        timed = "Morning efficiency: still online, still unimpressed by chaos."
    elif 22 <= hour or hour < 5:
        timed = "Late shift. I'll keep it sharp so you can sleep eventually."
    candidates = ([timed] if timed and _rubric_ok(timed) else []) + [
        q for q in _BANK if _rubric_ok(q)
    ]
    if context and "retry" in context.lower():
        candidates.insert(0, "Second try. Persistence is underrated.")
    for q in candidates:
        if q and _rubric_ok(q):
            _recent.append(q)
            return q
    return None


def maybe_append_quip(reply: str, *, user_text: str = "", is_error: bool = False,
                      is_security: bool = False, context: str = "") -> str:
    if not should_quip(user_text=user_text, reply=reply, is_error=is_error,
                       is_security=is_security):
        return reply
    # Already has a light closing quip? skip if reply already long
    if len((reply or "").split()) > 80:
        return reply
    quip = None
    if humor_level() in {"dry", "full"} and (os.environ.get("FRIDAY_MODEL_ROLES") or "").lower() in {
        "1", "true", "yes", "on",
    }:
        try:
            quip = _generate_quip(user_text=user_text, reply=reply, context=context)
        except Exception:
            quip = None
    if not quip:
        quip = pick_fallback_quip(context=context)
    if not quip or not _rubric_ok(quip):
        return reply
    _recent.append(quip)
    return f"{reply.rstrip()}\n\n{quip}"


def _generate_quip(*, user_text: str, reply: str, context: str) -> str | None:
    from friday.models.local import query_model_text
    from friday.models.roles import get_model_roles

    roles = get_model_roles()
    model = roles.fast if roles.enabled else None
    prompt = (
        "Write ONE short dry quip (max 15 words) for Friday the AI aide. "
        "Original only — no film quotes. No invented facts. "
        f"Context: {context[:80]}\nUser: {user_text[:120]}\nReply summary: {reply[:160]}\n"
        "Quip:"
    )
    out = query_model_text(
        prompt,
        format_json=False,
        think=False,
        num_predict=40,
        model=model,
    )
    line = (out.get("message") or out.get("raw") or "").strip().strip('"').split("\n")[0]
    return line if _rubric_ok(line) else None
