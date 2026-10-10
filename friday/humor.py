"""Humor policy: at most one short quip; never during errors/security/stress.

Suppression is decided BEFORE any model call (blocked_context), not only after.
"""

from __future__ import annotations

import json
import os
import re
import time
from collections import deque
from contextvars import ContextVar
from pathlib import Path
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
    r"couldn.?t|cannot|unable|bad news|refused)\b",
    re.I,
)
_SECURITY = re.compile(
    r"\b(passkey|pairing|approve|approval|shell|authorize|authentication|"
    r"step-?up|revoke|credential|token|password|without asking|"
    r"physical confirmation|security)\b",
    re.I,
)
_BAD_NEWS = re.compile(
    r"\b(sorry|unfortunately|could not|wasn't able|i failed|went wrong)\b",
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
    # Feedback can nudge dry→off when many recent downs
    base = (os.environ.get("FRIDAY_HUMOR") or "dry").strip().lower()
    if base not in {"off", "dry", "full"}:
        base = "dry"
    try:
        freq = feedback_store().suggested_level(base)
        return freq
    except Exception:  # noqa: BLE001
        return base


def blocked_context(
    *,
    user_text: str = "",
    reply: str = "",
    is_error: bool = False,
    is_security: bool = False,
    is_approval: bool = False,
    is_bad_news: bool = False,
) -> str | None:
    """Return a reason string if quips are forbidden; None if allowed.

    Called BEFORE any model generation so a quip is never requested in blocked contexts.
    """
    if humor_level() == "off":
        return "humor_off"
    if is_error or is_security or is_approval or is_bad_news:
        return "flag"
    if _STRESS.search(user_text or ""):
        return "stressed_owner"
    if _SECURITY.search(user_text or ""):
        return "security_prompt"
    if _ERR_MARKERS.search(reply or "") or _BAD_NEWS.search(reply or ""):
        return "error_or_bad_news_reply"
    if _SECURITY.search(reply or "") and _ERR_MARKERS.search(reply or ""):
        return "security_reply"
    return None


def should_quip(*, user_text: str = "", reply: str = "", is_error: bool = False,
                is_security: bool = False, is_approval: bool = False,
                is_bad_news: bool = False) -> bool:
    return blocked_context(
        user_text=user_text,
        reply=reply,
        is_error=is_error,
        is_security=is_security,
        is_approval=is_approval,
        is_bad_news=is_bad_news,
    ) is None


def _rubric_ok(line: str) -> bool:
    s = (line or "").strip()
    if not s or len(s) > 120:
        return False
    if s in _recent:
        return False
    banned = ("i am iron", "assemble", "jarvis", "stark industries", "suit up")
    low = s.lower()
    if any(b in low for b in banned):
        return False
    # Never append a quip that itself looks like a security/error line
    if _ERR_MARKERS.search(s) or _SECURITY.search(s):
        return False
    return True


def pick_fallback_quip(*, context: str = "") -> str | None:
    if humor_level() == "off":
        return None
    disliked = feedback_store().disliked_styles()
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
        if not q or not _rubric_ok(q):
            continue
        if any(d in q.lower() for d in disliked):
            continue
        _recent.append(q)
        return q
    return None


def maybe_append_quip(
    reply: str,
    *,
    user_text: str = "",
    is_error: bool = False,
    is_security: bool = False,
    is_approval: bool = False,
    is_bad_news: bool = False,
    context: str = "",
) -> str:
    reason = blocked_context(
        user_text=user_text,
        reply=reply,
        is_error=is_error,
        is_security=is_security,
        is_approval=is_approval,
        is_bad_news=is_bad_news,
    )
    if reason is not None:
        return reply
    if len((reply or "").split()) > 80:
        return reply
    # Frequency throttle from feedback
    if not feedback_store().allow_quip_now():
        return reply
    quip = None
    # Model-generated quips only when not blocked AND roles enabled — still after the gate.
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
    # Final hard stop: never attach if the combined reply trips security/error
    combined = f"{reply.rstrip()}\n\n{quip}"
    if blocked_context(user_text=user_text, reply=combined, is_security=is_security):
        return reply
    _recent.append(quip)
    return combined


def _generate_quip(*, user_text: str, reply: str, context: str) -> str | None:
    # Gate again immediately before the model call (Stage T hard rule).
    if blocked_context(user_text=user_text, reply=reply) is not None:
        return None
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


# ---------------------------------------------------------------------------
# Owner feedback (thumbs) — local JSON, bounded, deletable
# ---------------------------------------------------------------------------

class FeedbackStore:
    def __init__(self, path: Path | None = None) -> None:
        from friday.config import DATA_DIR

        self.path = path or Path(DATA_DIR) / "humor_feedback.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data: dict = {"entries": [], "version": 1}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                self.data.update(json.loads(self.path.read_text(encoding="utf-8")))
            except Exception:  # noqa: BLE001
                pass

    def save(self) -> None:
        # Bound to last 200 entries
        self.data["entries"] = list(self.data.get("entries") or [])[-200:]
        self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")

    def add(self, *, kind: str, vote: str, text: str = "", reply_id: str = "") -> dict:
        entry = {
            "id": f"{int(time.time() * 1000)}-{len(self.data.get('entries') or [])}",
            "kind": kind if kind in {"reply", "quip"} else "reply",
            "vote": "up" if vote == "up" else "down",
            "text": (text or "")[:400],
            "reply_id": (reply_id or "")[:64],
            "t": time.time(),
        }
        self.data.setdefault("entries", []).append(entry)
        self.save()
        return entry

    def list(self, limit: int = 50) -> list[dict]:
        return list(reversed(self.data.get("entries") or []))[:limit]

    def clear(self) -> int:
        n = len(self.data.get("entries") or [])
        self.data["entries"] = []
        self.save()
        return n

    def delete(self, entry_id: str) -> bool:
        before = len(self.data.get("entries") or [])
        self.data["entries"] = [e for e in (self.data.get("entries") or []) if e.get("id") != entry_id]
        self.save()
        return len(self.data["entries"]) < before

    def disliked_styles(self) -> list[str]:
        """Crude tokens from down-voted quips to avoid repeating."""
        out: list[str] = []
        for e in self.data.get("entries") or []:
            if e.get("vote") == "down" and e.get("kind") == "quip":
                words = [w.lower() for w in re.findall(r"[a-zA-Z']{4,}", e.get("text") or "")]
                out.extend(words[:3])
        return list(dict.fromkeys(out))[-20:]

    def suggested_level(self, base: str) -> str:
        recent = (self.data.get("entries") or [])[-30:]
        downs = sum(1 for e in recent if e.get("vote") == "down")
        ups = sum(1 for e in recent if e.get("vote") == "up")
        if downs >= 8 and downs > ups * 2:
            return "off"
        if downs >= 4 and base == "full":
            return "dry"
        return base

    def allow_quip_now(self) -> bool:
        """Throttle: after many downs, only quip every Nth opportunity."""
        recent = (self.data.get("entries") or [])[-20:]
        downs = sum(1 for e in recent if e.get("vote") == "down")
        if downs >= 6:
            # ~25% chance via time bucket
            return (int(time.time()) // 7) % 4 == 0
        if downs >= 3:
            return (int(time.time()) // 5) % 2 == 0
        return True


_fb: FeedbackStore | None = None


def feedback_store() -> FeedbackStore:
    global _fb
    if _fb is None:
        _fb = FeedbackStore()
    return _fb


def set_feedback_store(store: FeedbackStore | None) -> None:
    global _fb
    _fb = store
