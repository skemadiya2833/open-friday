"""Focus session timer, parking lot, and quiet mode (no sounds/nudges)."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from friday.config import DATA_DIR, ensure_data_dirs


def _state_path() -> Path:
    ensure_data_dirs()
    return Path(DATA_DIR) / "focus_session.json"


def _load() -> dict[str, Any]:
    p = _state_path()
    defaults: dict[str, Any] = {
        "quiet_mode": False,
        "active": None,
        "parking_lot": [],
        "history": [],
    }
    if not p.is_file():
        return defaults
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return defaults
    defaults.update(data)
    return defaults


def _save(data: dict[str, Any]) -> None:
    from friday.atomic import write_text_atomic

    write_text_atomic(_state_path(), json.dumps(data, indent=2))


def get_settings() -> dict[str, Any]:
    d = _load()
    return {"quiet_mode": bool(d.get("quiet_mode")), "active": d.get("active")}


def set_quiet_mode(enabled: bool) -> dict[str, Any]:
    data = _load()
    data["quiet_mode"] = bool(enabled)
    _save(data)
    return get_settings()


def quiet_mode_enabled() -> bool:
    return bool(_load().get("quiet_mode"))


def start_focus(*, minutes: int = 25, label: str = "") -> dict[str, Any]:
    minutes = max(5, min(int(minutes), 180))
    data = _load()
    now = time.time()
    session = {
        "id": str(uuid.uuid4()),
        "label": (label or "Focus").strip()[:120],
        "started_at": now,
        "ends_at": now + minutes * 60,
        "minutes": minutes,
    }
    data["active"] = session
    _save(data)
    return session


def stop_focus() -> dict[str, Any]:
    data = _load()
    active = data.get("active")
    if active:
        hist = data.setdefault("history", [])
        active = {**active, "ended_at": time.time()}
        hist.append(active)
        data["history"] = hist[-50:]
    data["active"] = None
    _save(data)
    return {"stopped": True, "last": active}


def focus_status() -> dict[str, Any]:
    data = _load()
    active = data.get("active")
    if not active:
        return {"running": False, "quiet_mode": bool(data.get("quiet_mode"))}
    now = time.time()
    remaining = max(0, int(float(active.get("ends_at", now)) - now))
    return {
        "running": remaining > 0,
        "remaining_seconds": remaining,
        "session": active,
        "quiet_mode": bool(data.get("quiet_mode")),
    }


def parking_lot_add(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        raise ValueError("text required")
    data = _load()
    item = {"id": str(uuid.uuid4()), "text": text[:500], "created_at": time.time()}
    data.setdefault("parking_lot", []).append(item)
    _save(data)
    return item


def parking_lot_list() -> list[dict[str, Any]]:
    return list(_load().get("parking_lot") or [])


def parking_lot_remove(item_id: str) -> bool:
    data = _load()
    before = len(data.get("parking_lot") or [])
    data["parking_lot"] = [p for p in (data.get("parking_lot") or []) if p.get("id") != item_id]
    if len(data["parking_lot"]) == before:
        return False
    _save(data)
    return True
