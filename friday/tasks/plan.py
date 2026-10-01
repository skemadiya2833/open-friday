"""Persistent day plan — 'what we're doing today' agenda items."""

from __future__ import annotations

import json
import time
import uuid
from datetime import date
from pathlib import Path
from typing import Any

from friday.config import DATA_DIR, ensure_data_dirs


def _plan_path() -> Path:
    ensure_data_dirs()
    return Path(DATA_DIR) / "today_plan.json"


def _today() -> str:
    return date.today().isoformat()


def _load() -> dict[str, Any]:
    path = _plan_path()
    if not path.exists():
        return {"date": _today(), "items": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"date": _today(), "items": []}
    if data.get("date") != _today():
        # Roll forward — keep incomplete items into the new day.
        carry = [
            {**it, "carried": True}
            for it in (data.get("items") or [])
            if not it.get("done")
        ]
        data = {"date": _today(), "items": carry}
        _save(data)
    return data


def _save(data: dict[str, Any]) -> None:
    _plan_path().write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_plan() -> dict[str, Any]:
    return _load()


def add_item(text: str, *, note: str = "") -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        raise ValueError("text required")
    data = _load()
    item = {
        "id": str(uuid.uuid4()),
        "text": text,
        "note": (note or "").strip(),
        "done": False,
        "created_at": time.time(),
    }
    data.setdefault("items", []).append(item)
    _save(data)
    return item


def set_done(item_id: str, done: bool = True) -> dict[str, Any] | None:
    data = _load()
    for it in data.get("items") or []:
        if it.get("id") == item_id:
            it["done"] = bool(done)
            _save(data)
            return it
    return None


def remove_item(item_id: str) -> bool:
    data = _load()
    before = len(data.get("items") or [])
    data["items"] = [it for it in (data.get("items") or []) if it.get("id") != item_id]
    if len(data["items"]) == before:
        return False
    _save(data)
    return True


def format_for_prompt() -> str:
    data = _load()
    items = data.get("items") or []
    if not items:
        return "(no agenda items for today)"
    lines = []
    for it in items:
        mark = "[x]" if it.get("done") else "[ ]"
        note = f" — {it['note']}" if it.get("note") else ""
        lines.append(f"{mark} {it.get('text', '')}{note}")
    return "\n".join(lines)
