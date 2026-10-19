"""Local fine-tune corpus — every turn + owner good/bad labels.

Writes under ``training/`` at the repo root (gitignored). Use thumbs in the UI
or ``rate_turn`` to mark quality; ``export_day`` joins turns + ratings into a
ShareGPT-style JSONL for later fine-tuning.
"""

from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Literal

Vote = Literal["up", "down", "good", "bad"]

_lock = threading.Lock()

_GLITCH = re.compile(
    r"(?i)\b(i glitched|say it once more|blanked on that|no reply came back)\b"
)


def training_root() -> Path:
    from friday.config import TRAINING_DIR

    root = Path(TRAINING_DIR)
    root.mkdir(parents=True, exist_ok=True)
    (root / "turns").mkdir(exist_ok=True)
    (root / "ratings").mkdir(exist_ok=True)
    (root / "daily").mkdir(exist_ok=True)
    return root


def _day_key(day: date | None = None) -> str:
    return (day or date.today()).isoformat()


def _turns_path(day: date | None = None) -> Path:
    return training_root() / "turns" / f"{_day_key(day)}.jsonl"


def _ratings_path(day: date | None = None) -> Path:
    return training_root() / "ratings" / f"{_day_key(day)}.jsonl"


def _daily_path(day: date | None = None) -> Path:
    return training_root() / "daily" / f"{_day_key(day)}.jsonl"


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(row, ensure_ascii=False, default=str)
    with _lock:
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def _current_model() -> str:
    try:
        from friday.config import resolve_chat_model

        return resolve_chat_model()
    except Exception:  # noqa: BLE001
        return ""


def _auto_signals(reply: str, meta: dict[str, Any] | None) -> list[str]:
    """Weak automatic labels — owner thumbs still win."""
    flags: list[str] = []
    text = (reply or "").strip()
    if not text:
        flags.append("empty_reply")
    if _GLITCH.search(text):
        flags.append("glitch_fallback")
    try:
        from friday.assistant.reply_guard import looks_like_prompt_dump

        if looks_like_prompt_dump(text):
            flags.append("prompt_dump")
    except Exception:  # noqa: BLE001
        pass
    if meta and meta.get("error"):
        flags.append("skill_error")
    if meta and meta.get("fallback_plain"):
        flags.append("report_fallback")
    return flags


def log_training_turn(
    *,
    user: str,
    reply: str,
    skill: str | None = None,
    intent: dict[str, Any] | None = None,
    session_id: str | None = None,
    voice: bool = False,
    meta: dict[str, Any] | None = None,
    model: str | None = None,
) -> str:
    """Append one training turn. Returns ``turn_id`` for later rating."""
    turn_id = uuid.uuid4().hex
    tools = []
    if meta and isinstance(meta.get("tools"), list):
        tools = meta.get("tools") or []
    row = {
        "turn_id": turn_id,
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "session_id": session_id or "",
        "voice": bool(voice),
        "model": (model or _current_model())[:120],
        "skill": skill or "",
        "intent": intent or {},
        "user": (user or "")[:4000],
        "reply": (reply or "")[:8000],
        "tools": tools[:20] if isinstance(tools, list) else [],
        "meta": {
            k: (meta or {}).get(k)
            for k in (
                "report_id",
                "open_report",
                "open_findings",
                "fallback_plain",
                "error",
                "learned",
            )
            if meta and k in meta
        },
        "auto_flags": _auto_signals(reply, meta),
    }
    try:
        _append_jsonl(_turns_path(), row)
    except Exception as exc:  # noqa: BLE001
        print(f"[TrainingLog] turn write failed: {exc}", flush=True)
    return turn_id


def rate_turn(
    turn_id: str,
    vote: Vote,
    *,
    note: str = "",
    reply_excerpt: str = "",
) -> dict[str, Any]:
    """Record owner quality label for a turn (good/bad)."""
    tid = (turn_id or "").strip()
    if not tid:
        return {"ok": False, "error": "missing turn_id"}
    label = "good" if vote in {"up", "good"} else "bad"
    row = {
        "turn_id": tid,
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "label": label,
        "vote": "up" if label == "good" else "down",
        "note": (note or "")[:400],
        "reply_excerpt": (reply_excerpt or "")[:400],
    }
    try:
        _append_jsonl(_ratings_path(), row)
    except Exception as exc:  # noqa: BLE001
        print(f"[TrainingLog] rating write failed: {exc}", flush=True)
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "entry": row}


def _latest_ratings(day: date | None = None) -> dict[str, dict[str, Any]]:
    """Last rating wins per turn_id."""
    by_id: dict[str, dict[str, Any]] = {}
    for row in _read_jsonl(_ratings_path(day)):
        tid = str(row.get("turn_id") or "")
        if tid:
            by_id[tid] = row
    return by_id


def list_day(day: date | None = None) -> list[dict[str, Any]]:
    """Turns for a day with latest rating attached (if any)."""
    ratings = _latest_ratings(day)
    out: list[dict[str, Any]] = []
    for row in _read_jsonl(_turns_path(day)):
        tid = str(row.get("turn_id") or "")
        rated = ratings.get(tid)
        item = dict(row)
        if rated:
            item["label"] = rated.get("label")
            item["rated_at"] = rated.get("ts")
            item["rating_note"] = rated.get("note") or ""
        else:
            item["label"] = None
        out.append(item)
    return out


def day_summary(day: date | None = None) -> dict[str, Any]:
    rows = list_day(day)
    good = sum(1 for r in rows if r.get("label") == "good")
    bad = sum(1 for r in rows if r.get("label") == "bad")
    unrated = sum(1 for r in rows if not r.get("label"))
    flagged = sum(1 for r in rows if r.get("auto_flags"))
    return {
        "date": _day_key(day),
        "turns": len(rows),
        "good": good,
        "bad": bad,
        "unrated": unrated,
        "auto_flagged": flagged,
        "path": str(_turns_path(day)),
    }


def export_day(day: date | None = None, *, labeled_only: bool = False) -> Path:
    """Write ShareGPT-style daily JSONL under ``training/daily/`` for fine-tune."""
    rows = list_day(day)
    if labeled_only:
        rows = [r for r in rows if r.get("label") in {"good", "bad"}]
    path = _daily_path(day)
    lines: list[str] = []
    for r in rows:
        sample = {
            "turn_id": r.get("turn_id"),
            "label": r.get("label"),
            "model": r.get("model"),
            "skill": r.get("skill"),
            "auto_flags": r.get("auto_flags") or [],
            "conversations": [
                {"from": "human", "value": r.get("user") or ""},
                {"from": "gpt", "value": r.get("reply") or ""},
            ],
            # Preference pair helpers (use good vs bad across the day when filtering).
            "preference": r.get("label"),
        }
        lines.append(json.dumps(sample, ensure_ascii=False, default=str))
    with _lock:
        path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return path
