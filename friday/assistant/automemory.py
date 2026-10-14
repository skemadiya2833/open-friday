"""Automatic long-term memory — only durable facts, routed to the right store.

Chat turns stay in the session JSON. This module never dumps whole messages.

Routing:
* **sqlite** — stable owner profile facts (name, place, work, durable prefs).
  Injected into prompts via ``owner_facts``; no Chroma mirror needed.
* **both** — freeform notes worth semantic recall later (explicit "remember that…",
  longer durable context). SQLite for Memory Core UI + Chroma for RAG.
* Skip ephemeral chatter, questions, secrets, and reminder-shaped lines.
"""

from __future__ import annotations

import hashlib
import re
import threading
from dataclasses import dataclass
from typing import Literal

Store = Literal["sqlite", "both"]

_SECRET = re.compile(
    r"(password|passcode|pin\b|otp|cvv|card number|credit card|api[_ -]?key|secret|token|"
    r"ssn|aadhaar|\b\d{12,19}\b)",
    re.I,
)
_QUESTION = re.compile(r"^\s*(what|who|where|when|why|how|do you|can you|did|are you)\b|\?\s*$", re.I)
# "remember to buy milk" is a task, not a fact.
_REMEMBER_TASK = re.compile(r"\b(?:remember|don'?t forget)\s+to\b", re.I)
_EPHEMERAL = re.compile(
    r"\b("
    r"tired|hungry|thirsty|busy|late|sick|bored|stressed|angry|upset|"
    r"going|leaving|heading|about to|right now|for now|at the moment|"
    r"today|tonight|this (morning|afternoon|evening|week)|"
    r"that (idea|one|thing|option)|this (one|thing|option)|the other one"
    r")\b",
    re.I,
)
_DEICTIC_OBJ = re.compile(
    r"^(?:that|this|it|one|him|her|them|you|these|those)\b",
    re.I,
)
_DURABLE_ROLE = re.compile(
    r"\bi(?:'m| am) (?:a|an)\s+("
    r"(?:software |web |senior |junior |full[- ]?stack |backend |frontend )?"
    r"(?:engineer|developer|designer|student|teacher|doctor|lawyer|founder|ceo|"
    r"manager|writer|artist|musician|researcher|consultant|freelancer|founder)"
    r"[\w &'’.-]{0,40}"
    r")",
    re.I,
)


@dataclass(frozen=True)
class MemoryCandidate:
    text: str
    store: Store
    kind: str = "fact"  # fact | note


# Explicit patterns → (template, default store). store may be overridden by filters.
_PATTERNS: list[tuple[re.Pattern[str], str, Store]] = [
    (re.compile(r"\b(?:remember|note|keep in mind|don'?t forget)(?: that)?[,:]?\s+(.{8,200})", re.I), "{0}", "both"),
    (re.compile(r"\bmy name(?: is|'s)\s+([A-Za-z][\w'’ -]{1,40})", re.I), "The owner's name is {0}", "sqlite"),
    (re.compile(r"\b(?:call me|you can call me)\s+([A-Za-z][\w'’-]{1,30})", re.I), "The owner likes to be called {0}", "sqlite"),
    (re.compile(r"\bi (?:live|stay|am based) in\s+([A-Za-z][\w ,'’-]{1,60})", re.I), "The owner lives in {0}", "sqlite"),
    (re.compile(r"\bi work (?:at|for|as)\s+([\w &.'’-]{2,60})", re.I), "The owner works {0}", "sqlite"),
    (
        re.compile(
            r"\bi (love|like|enjoy|hate|dislike|prefer)\s+([^.!?\n]{3,80})",
            re.I,
        ),
        "The owner {0}s {1}",
        "sqlite",
    ),
    (
        re.compile(
            r"\bmy (favou?rite [\w ]{2,25}|birthday|wife|husband|partner|girlfriend|boyfriend|"
            r"mother|mom|father|dad|brother|sister|dog|cat|boss|manager|email|phone|"
            r"timezone|editor|browser|os|laptop|pc) (?:is|are)\s+([^.!?\n]{2,80})",
            re.I,
        ),
        "The owner's {0} is {1}",
        "sqlite",
    ),
]


def _worth_keeping(text: str, *, store: Store) -> Store | None:
    """Return the store to use, or None to discard."""
    t = (text or "").strip()
    if len(t) < 8 or len(t) > 400:
        return None
    if _SECRET.search(t) or _EPHEMERAL.search(t):
        return None
    # Profile facts stay sqlite-only; freeform notes may use Chroma.
    if store == "both" and len(t) < 24 and not re.search(r"\b(is|in|at|near|called)\b", t, re.I):
        # Very short "remember that X" without structure — still allow if not ephemeral.
        pass
    return store


def _from_like(verb: str, obj: str) -> MemoryCandidate | None:
    obj = obj.strip(" .,!;:")
    if not obj or _DEICTIC_OBJ.search(obj) or _EPHEMERAL.search(obj):
        return None
    # "I like that" / "I prefer this approach for now" already filtered; keep durable prefs.
    fact = f"The owner {verb}s {obj}"[:240]
    store = _worth_keeping(fact, store="sqlite")
    if not store:
        return None
    return MemoryCandidate(text=fact, store=store, kind="fact")


def extract_candidates(message: str) -> list[MemoryCandidate]:
    msg = (message or "").strip()
    if not msg or len(msg) > 600:
        return []
    if _SECRET.search(msg) or _QUESTION.search(msg) or _REMEMBER_TASK.search(msg):
        return []

    out: list[MemoryCandidate] = []

    role = _DURABLE_ROLE.search(msg)
    if role:
        fact = f"The owner is a {role.group(1).strip(' .,!;:')}"[:240]
        store = _worth_keeping(fact, store="sqlite")
        if store:
            out.append(MemoryCandidate(text=fact, store=store, kind="fact"))

    for pat, tmpl, default_store in _PATTERNS:
        m = pat.search(msg)
        if not m:
            continue
        groups = [g.strip(" .,!;:") for g in m.groups()]
        if tmpl == "The owner {0}s {1}" and len(groups) >= 2:
            cand = _from_like(groups[0].lower(), groups[1])
            if cand:
                out.append(cand)
            continue
        fact = tmpl.format(*groups)[:240]
        # Explicit remember-notes are freeform → both (if worth it).
        store = _worth_keeping(fact, store=default_store)
        if store:
            kind = "note" if default_store == "both" else "fact"
            out.append(MemoryCandidate(text=fact, store=store, kind=kind))

    # Dedupe by normalized text, prefer "both" over sqlite-only.
    ranked: dict[str, MemoryCandidate] = {}
    for c in out:
        key = re.sub(r"\W+", " ", c.text.lower()).strip()
        prev = ranked.get(key)
        if prev is None or (prev.store == "sqlite" and c.store == "both"):
            ranked[key] = c
    return list(ranked.values())


def extract(message: str) -> list[str]:
    """Backward-compatible: texts only."""
    return [c.text for c in extract_candidates(message)]


def _id(text: str) -> str:
    return "auto-" + hashlib.sha1(re.sub(r"\W+", " ", text.lower()).strip().encode()).hexdigest()[:20]


def remember(message: str, *, background: bool = True) -> list[str]:
    """Store worth-keeping facts. Returns texts that were accepted."""
    cands = extract_candidates(message)
    if not cands:
        return []

    def _store() -> None:
        try:
            from friday.store.facts import add_fact

            for c in cands:
                add_fact(
                    c.text,
                    source="auto",
                    kind=c.kind,
                    fact_id=_id(c.text),
                    mirror_chroma=(c.store == "both"),
                )
        except Exception as exc:  # noqa: BLE001 - memory must never break chat
            print(f"[Memory] auto-remember skipped: {exc}")

    if background:
        threading.Thread(target=_store, daemon=True, name="FridayAutoMemory").start()
    else:
        _store()
    return [c.text for c in cands]


def owner_facts(limit: int = 12) -> list[str]:
    """Most recent stored facts about the owner — SQLite only, no embedding call."""
    try:
        from friday.store.facts import list_facts

        return list_facts(limit=limit)
    except Exception:  # noqa: BLE001
        return []
