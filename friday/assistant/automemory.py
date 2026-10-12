"""Automatic long-term memory: remember durable facts the owner states, without being asked.

Deterministic extraction (no model call, no latency): "my name is ...", "I live in ...", "I like/love/hate/prefer ...",
"my <thing> is ...", "remember that ...". Everything stored is visible and deletable in the Memory view
(metadata ``source=auto``); sensitive-looking text (passwords, card numbers, keys) is never stored.
"""

from __future__ import annotations

import hashlib
import re
import threading
from typing import Any

_SECRET = re.compile(r"(password|passcode|pin\b|otp|cvv|card number|credit card|api[_ -]?key|secret|token|ssn|aadhaar|\b\d{12,19}\b)", re.I)

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(?:remember|note|keep in mind|don'?t forget)(?: that)?[,:]?\s+(.{4,200})", re.I), "{0}"),
    (re.compile(r"\bmy name(?: is|'s)\s+([A-Za-z][\w'’ -]{1,40})", re.I), "The owner's name is {0}"),
    (re.compile(r"\b(?:call me|you can call me)\s+([A-Za-z][\w'’-]{1,30})", re.I), "The owner likes to be called {0}"),
    (re.compile(r"\bi (?:live|stay|am based) in\s+([A-Za-z][\w ,'’-]{1,60})", re.I), "The owner lives in {0}"),
    (re.compile(r"\bi(?:'m| am) (?:a|an)\s+([A-Za-z][\w -]{2,50})", re.I), "The owner is a {0}"),
    (re.compile(r"\bi work (?:at|for|as)\s+([\w &.'’-]{2,60})", re.I), "The owner works {0}"),
    (re.compile(r"\bi (love|like|enjoy|hate|dislike|prefer)\s+([^.!?\n]{3,80})", re.I), "The owner {0}s {1}"),
    (re.compile(r"\bmy (favou?rite [\w ]{2,25}|birthday|wife|husband|partner|girlfriend|boyfriend|mother|mom|father|dad|brother|sister|dog|cat|boss|manager|email|phone|timezone|editor|browser|os|laptop|pc) (?:is|are)\s+([^.!?\n]{2,80})", re.I), "The owner's {0} is {1}"),
]
_QUESTION = re.compile(r"^\s*(what|who|where|when|why|how|do you|can you|did)\b|\?\s*$", re.I)


def extract(message: str) -> list[str]:
    msg = (message or "").strip()
    if not msg or len(msg) > 600 or _SECRET.search(msg) or _QUESTION.search(msg):
        return []
    out: list[str] = []
    for pat, tmpl in _PATTERNS:
        m = pat.search(msg)
        if not m:
            continue
        groups = [g.strip(" .,!;:") for g in m.groups()]
        fact = tmpl.format(*groups)
        out.append(fact[:240])
    return list(dict.fromkeys(out))


def _id(text: str) -> str:
    return "auto-" + hashlib.sha1(re.sub(r"\W+", " ", text.lower()).strip().encode()).hexdigest()[:20]


def remember(message: str, *, background: bool = True) -> list[str]:
    """Store extracted facts (idempotent). Returns the facts found."""
    facts = extract(message)
    if not facts:
        return []

    def _store() -> None:
        try:
            from friday.memory import get_memory

            for f in facts:
                get_memory().add(f, metadata={"source": "auto", "kind": "fact"}, doc_id=_id(f))
        except Exception as exc:  # noqa: BLE001 - memory must never break chat
            print(f"[Memory] auto-remember skipped: {exc}")

    if background:
        threading.Thread(target=_store, daemon=True, name="FridayAutoMemory").start()
    else:
        _store()
    return facts


def owner_facts(limit: int = 12) -> list[str]:
    """Most recent stored facts about the owner (auto + manually added), for the chat prompt. No embedding call."""
    try:
        from friday.memory import get_memory

        hits = get_memory().list_all(collection="memories", limit=200)
    except Exception:  # noqa: BLE001
        return []
    rows: list[Any] = [h for h in hits if (h.metadata or {}).get("source") != "computer_use"]
    rows.sort(key=lambda h: float((h.metadata or {}).get("created_at", 0) or 0), reverse=True)
    return [h.text for h in rows[:limit]]
