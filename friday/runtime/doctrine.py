"""Learned operating principles — from “read articles and learn” turns.

Stored under ``data/doctrine.json`` (gitignored via ``data/``). Injected into
chat/agent prompts so future actions reflect what Friday studied — not fed as
raw article dumps.
"""

from __future__ import annotations

import json
import re
import threading
import time
from typing import Any

from friday.atomic import write_text_atomic

_lock = threading.RLock()
_MAX_TOPICS = 24
_MAX_BULLETS = 12


def _path():
    from pathlib import Path

    from friday.config import DATA_DIR

    return Path(DATA_DIR) / "doctrine.json"


def load() -> dict[str, Any]:
    path = _path()
    if not path.is_file():
        return {"topics": {}, "updated": 0}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and isinstance(raw.get("topics"), dict):
            return raw
    except Exception:  # noqa: BLE001
        pass
    return {"topics": {}, "updated": 0}


def save(data: dict[str, Any]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        write_text_atomic(path, json.dumps(data, indent=2) + "\n")


def add_lessons(
    topic: str,
    bullets: list[str],
    *,
    sources: list[str] | None = None,
) -> dict[str, Any]:
    """Merge distilled lessons for a topic. Returns the stored topic record."""
    topic = re.sub(r"\s+", " ", (topic or "").strip())[:120]
    if not topic:
        raise ValueError("empty topic")
    clean = []
    seen: set[str] = set()
    for b in bullets or []:
        line = re.sub(r"\s+", " ", str(b or "").strip())[:240]
        if len(line) < 12:
            continue
        key = line.lower()
        if key in seen:
            continue
        seen.add(key)
        clean.append(line)
        if len(clean) >= _MAX_BULLETS:
            break
    if not clean:
        raise ValueError("no lessons")
    key = re.sub(r"\W+", " ", topic.lower()).strip() or "general"
    with _lock:
        data = load()
        topics = data.setdefault("topics", {})
        prev = topics.get(key) or {}
        merged = list(prev.get("bullets") or [])
        for line in clean:
            if line.lower() not in {x.lower() for x in merged}:
                merged.append(line)
        merged = merged[-_MAX_BULLETS:]
        srcs = list(prev.get("sources") or [])
        for s in sources or []:
            s = str(s).strip()[:300]
            if s and s not in srcs:
                srcs.append(s)
        rec = {
            "topic": topic,
            "bullets": merged,
            "sources": srcs[-8:],
            "updated": time.time(),
        }
        topics[key] = rec
        if len(topics) > _MAX_TOPICS:
            ranked = sorted(topics.items(), key=lambda kv: float(kv[1].get("updated") or 0))
            for k, _ in ranked[: len(topics) - _MAX_TOPICS]:
                topics.pop(k, None)
        data["updated"] = time.time()
        save(data)
        return rec


def prompt_block(limit_topics: int = 4, limit_bullets: int = 8) -> str:
    data = load()
    topics = list((data.get("topics") or {}).values())
    topics.sort(key=lambda e: float(e.get("updated") or 0), reverse=True)
    lines: list[str] = []
    for t in topics[:limit_topics]:
        title = str(t.get("topic") or "").strip()
        for b in (t.get("bullets") or [])[: max(1, limit_bullets // max(1, limit_topics))]:
            lines.append(f"[{title}] {b}" if title else str(b))
        if len(lines) >= limit_bullets:
            break
    if not lines:
        return ""
    return (
        "Learned doctrine (from articles you studied — apply in actions, do not recite as a lecture):\n- "
        + "\n- ".join(lines[:limit_bullets])
    )
