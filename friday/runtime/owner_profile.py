"""Owner profile — how Friday should know you, plus product upgrade notes.

Stored in ``data/owner_profile.json``. About-me text is injected into chat prompts.
Upgrade notes are durable ideas Friday (or you) record for future work.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any

from friday.atomic import write_text_atomic

_lock = threading.RLock()
_MAX_ABOUT = 4000
_MAX_UPGRADES = 40
_MAX_UPGRADE_LEN = 280


def _path():
    from pathlib import Path

    from friday.config import DATA_DIR

    return Path(DATA_DIR) / "owner_profile.json"


def load() -> dict[str, Any]:
    path = _path()
    if not path.is_file():
        return {"about": "", "upgrades": []}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {"about": "", "upgrades": []}
        about = str(raw.get("about") or "")[:_MAX_ABOUT]
        upgrades: list[dict[str, Any]] = []
        for u in raw.get("upgrades") or []:
            if isinstance(u, str) and u.strip():
                upgrades.append({"text": u.strip()[:_MAX_UPGRADE_LEN], "ts": 0, "source": "manual"})
            elif isinstance(u, dict) and str(u.get("text") or "").strip():
                upgrades.append(
                    {
                        "text": str(u["text"]).strip()[:_MAX_UPGRADE_LEN],
                        "ts": float(u.get("ts") or 0),
                        "source": str(u.get("source") or "manual")[:32],
                    }
                )
            if len(upgrades) >= _MAX_UPGRADES:
                break
        return {"about": about, "upgrades": upgrades}
    except Exception:  # noqa: BLE001
        return {"about": "", "upgrades": []}


def save(data: dict[str, Any]) -> dict[str, Any]:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = {
        "about": str(data.get("about") or "")[:_MAX_ABOUT],
        "upgrades": list(data.get("upgrades") or [])[:_MAX_UPGRADES],
    }
    with _lock:
        write_text_atomic(path, json.dumps(clean, indent=2) + "\n")
    return clean


def update(*, about: str | None = None, upgrades: list | None = None) -> dict[str, Any]:
    with _lock:
        data = load()
        if about is not None:
            data["about"] = about[:_MAX_ABOUT]
        if upgrades is not None:
            data["upgrades"] = upgrades[:_MAX_UPGRADES]
        return save(data)


def add_upgrade(text: str, *, source: str = "manual") -> dict[str, Any]:
    text = (text or "").strip()[:_MAX_UPGRADE_LEN]
    if not text:
        raise ValueError("text required")
    with _lock:
        data = load()
        # De-dupe case-insensitively
        low = text.lower()
        existing = [u for u in data["upgrades"] if str(u.get("text") or "").lower() != low]
        existing.insert(0, {"text": text, "ts": time.time(), "source": (source or "manual")[:32]})
        data["upgrades"] = existing[:_MAX_UPGRADES]
        return save(data)


def about_text() -> str:
    return str(load().get("about") or "").strip()


def upgrade_lines(limit: int = 12) -> list[str]:
    ups = load().get("upgrades") or []
    out: list[str] = []
    for u in ups:
        t = str(u.get("text") or "").strip()
        if t:
            out.append(t)
        if len(out) >= limit:
            break
    return out


def prompt_block() -> str:
    """Compact block for system prompts (chat / voice / agent)."""
    about = about_text()
    ups = upgrade_lines(8)
    parts: list[str] = []
    if about:
        parts.append("Owner profile (from Systems — treat as durable context):\n" + about.strip())
    if ups:
        parts.append(
            "Known upgrade ideas (do not read aloud unless asked; append new ones sparingly "
            "when the owner clearly wants a future product improvement):\n- "
            + "\n- ".join(ups)
        )
    if not parts:
        return ""
    parts.append(
        "When the owner describes a clear Friday product improvement to remember, "
        "reply briefly and include a single line exactly like: UPGRADE: <short idea>."
    )
    return "\n\n".join(parts)
