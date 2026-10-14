"""Light knowledge graph — entities from chat for session continuity.

Deterministic extract (no model). Complements owner facts + diary.
"""

from __future__ import annotations

import json
import re
import threading
import time
from typing import Any

from friday.atomic import write_text_atomic

_lock = threading.RLock()
_MAX_ENTITIES = 80

_PROJECT = re.compile(
    r"(?:working on|building|shipping|fixing|debugging)\s+([A-Za-z][\w .'-]{2,40})",
    re.I,
)
_PERSON = re.compile(r"\b(?:met|call|email|ping|message)\s+([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\b")
_TOOL = re.compile(r"\b(?:using|switched to|prefer)\s+([A-Za-z][\w .+-]{2,30})", re.I)


def _path():
    from pathlib import Path

    from friday.config import DATA_DIR

    return Path(DATA_DIR) / "knowledge.json"


def load() -> dict[str, Any]:
    path = _path()
    if not path.is_file():
        return {"entities": {}, "updated": 0}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and isinstance(raw.get("entities"), dict):
            return raw
    except Exception:  # noqa: BLE001
        pass
    return {"entities": {}, "updated": 0}


def save(data: dict[str, Any]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        write_text_atomic(path, json.dumps(data, indent=2) + "\n")


def observe(message: str) -> list[str]:
    """Extract and store entities from a user turn. Returns new/updated labels."""
    msg = (message or "").strip()
    if len(msg) < 8 or len(msg) > 400:
        return []
    found: list[tuple[str, str]] = []
    for pat, kind in ((_PROJECT, "project"), (_PERSON, "person"), (_TOOL, "tool")):
        for m in pat.finditer(msg):
            label = m.group(1).strip(" .,!;:'\"")
            if len(label) >= 2:
                found.append((label, kind))
    if not found:
        return []
    with _lock:
        data = load()
        ents = data.setdefault("entities", {})
        touched: list[str] = []
        now = time.time()
        for label, kind in found:
            key = re.sub(r"\W+", " ", label.lower()).strip()
            if not key:
                continue
            prev = ents.get(key) or {}
            ents[key] = {
                "label": label[:80],
                "kind": kind,
                "hits": int(prev.get("hits") or 0) + 1,
                "updated": now,
            }
            touched.append(label[:80])
        # Cap size by oldest
        if len(ents) > _MAX_ENTITIES:
            ranked = sorted(ents.items(), key=lambda kv: float(kv[1].get("updated") or 0))
            for k, _ in ranked[: len(ents) - _MAX_ENTITIES]:
                ents.pop(k, None)
        data["updated"] = now
        save(data)
        return touched


def continuity_lines(limit: int = 5) -> list[str]:
    data = load()
    ents = list((data.get("entities") or {}).values())
    ents.sort(key=lambda e: float(e.get("updated") or 0), reverse=True)
    out: list[str] = []
    for e in ents[:limit]:
        label = str(e.get("label") or "").strip()
        kind = str(e.get("kind") or "topic")
        if label:
            out.append(f"{kind}: {label}")
    return out


def prompt_block(limit: int = 5) -> str:
    lines = continuity_lines(limit)
    if not lines:
        return ""
    return (
        "Recent focus (knowledge graph — use naturally, do not recite as a list):\n- "
        + "\n- ".join(lines)
    )
