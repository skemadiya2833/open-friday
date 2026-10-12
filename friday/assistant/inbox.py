"""Local capture inbox — text now; voice can call the same add()."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from friday.config import DATA_DIR, ensure_data_dirs


def _path() -> Path:
    ensure_data_dirs()
    return Path(DATA_DIR) / "assistant_inbox.json"


def _load() -> dict[str, Any]:
    p = _path()
    if not p.is_file():
        return {"items": []}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"items": []}


def _save(data: dict[str, Any]) -> None:
    from friday.atomic import write_text_atomic

    write_text_atomic(_path(), json.dumps(data, indent=2))


def add(text: str, *, source: str = "text") -> dict[str, Any]:
    """Capture a task or note (voice hooks use this entry point)."""
    text = (text or "").strip()
    if not text:
        raise ValueError("text required")
    data = _load()
    item = {
        "id": str(uuid.uuid4()),
        "text": text[:2000],
        "source": source if source in {"text", "voice", "api"} else "text",
        "status": "open",
        "created_at": time.time(),
    }
    data.setdefault("items", []).append(item)
    _save(data)
    return item


def list_items(*, limit: int = 50, status: str | None = "open") -> list[dict[str, Any]]:
    items = list(_load().get("items") or [])
    if status:
        items = [i for i in items if i.get("status") == status]
    items.sort(key=lambda i: float(i.get("created_at") or 0), reverse=True)
    return items[: max(1, min(limit, 200))]


def review_summary(limit: int = 20) -> dict[str, Any]:
    open_items = list_items(limit=limit, status="open")
    return {
        "count": len(open_items),
        "items": open_items,
        "hint": "Skim, delete, or move to plan when you're ready — no inbox zero required.",
    }


def set_status(item_id: str, status: str) -> dict[str, Any] | None:
    if status not in {"open", "done", "dismissed"}:
        raise ValueError("invalid status")
    data = _load()
    for it in data.get("items") or []:
        if it.get("id") == item_id:
            it["status"] = status
            it["updated_at"] = time.time()
            _save(data)
            return it
    return None
