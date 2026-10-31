"""Humor level prefs + feedback — wit lives in the model's reply, not bolted banks.

`maybe_append_quip` is a no-op passthrough kept for call-site compatibility.
Never glue stock lines ("Coffee optional…") onto answers.
"""

from __future__ import annotations

import json
import os
import re
import time
from contextvars import ContextVar
from pathlib import Path

# Per-request override from the Control Center Settings page.
_humor_override: ContextVar[str | None] = ContextVar(
    "friday_humor_override", default=None
)

_STRESS = re.compile(
    r"\b(urgent|emergency|asap|angry|upset|furious|crisis|panic|help me now|"
    r"something.?s wrong|broken|disaster)\b",
    re.IGNORECASE,
)
_ERR_MARKERS = re.compile(
    r"\b(error|failed|failure|denied|blocked|unauthorized|approval required|"
    r"couldn.?t|can'?t|cannot|unable|bad news|refused|"
    r"don'?t have access|no access to|internal knowledge base|"
    r"can'?t browse|cannot browse|unable to browse)\b",
    re.IGNORECASE,
)
_SECURITY = re.compile(
    r"\b(passkey|pairing|approve|approval|shell|authorize|authentication|"
    r"step-?up|revoke|credential|token|password|without asking|"
    r"physical confirmation|security)\b",
    re.IGNORECASE,
)
_BAD_NEWS = re.compile(
    r"\b(sorry|unfortunately|could not|wasn't able|i failed|went wrong)\b",
    re.IGNORECASE,
)


def set_humor_override(level: str | None):
    """Context-local override (e.g. from chat request). Pass None to clear."""
    if level is None:
        _humor_override.set(None)
        return
    v = level.strip().lower()
    _humor_override.set(v if v in {"off", "dry", "full", "roast"} else None)


def humor_level() -> str:
    ov = _humor_override.get()
    if ov in {"off", "dry", "full", "roast"}:
        return ov
    # Feedback can nudge dry→off when many recent downs. Roast is opt-in only.
    try:
        from friday.runtime.prefs import get as pref

        base = str(pref("humor") or "dry").strip().lower()
    except Exception:  # noqa: BLE001
        base = (os.environ.get("FRIDAY_HUMOR") or "dry").strip().lower()
    if base not in {"off", "dry", "full", "roast"}:
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
    """Return a reason if bolted humor would be wrong — used by tests / callers.

    The model owns wit inside the main reply; we no longer append anything.
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


def should_quip(
    *,
    user_text: str = "",
    reply: str = "",
    is_error: bool = False,
    is_security: bool = False,
    is_approval: bool = False,
    is_bad_news: bool = False,
) -> bool:
    """Legacy name — always False; no post-hoc quip pipeline."""
    return False


def pick_fallback_quip(*, context: str = "") -> str | None:
    """Removed stock bank — always None."""
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
    """Passthrough — wit belongs in the model's answer, not a glued second paragraph."""
    return reply


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
        self.data["entries"] = [
            e for e in (self.data.get("entries") or []) if e.get("id") != entry_id
        ]
        self.save()
        return len(self.data["entries"]) < before

    def disliked_styles(self) -> list[str]:
        """Crude tokens from down-voted lines (prefs / future prompt nudges)."""
        out: list[str] = []
        for e in self.data.get("entries") or []:
            if e.get("vote") == "down" and e.get("kind") == "quip":
                words = [
                    w.lower() for w in re.findall(r"[a-zA-Z']{4,}", e.get("text") or "")
                ]
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
        """Unused for appends; kept for API compatibility."""
        return False


_fb: FeedbackStore | None = None


def feedback_store() -> FeedbackStore:
    global _fb
    if _fb is None:
        _fb = FeedbackStore()
    return _fb


def set_feedback_store(store: FeedbackStore | None) -> None:
    global _fb
    _fb = store
