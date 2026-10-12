"""Owner prefs for phone access (Systems / Devices UI). Overrides FRIDAY_AUTH=local → lan."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

_lock = threading.Lock()


def _path() -> Path:
    from friday.config import DATA_DIR

    return Path(DATA_DIR) / "auth_prefs.json"


def load_auth_prefs() -> dict[str, Any]:
    path = _path()
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def save_auth_prefs(update: dict[str, Any]) -> dict[str, Any]:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        data = load_auth_prefs()
        data.update(update)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return dict(data)


def phone_access_enabled() -> bool:
    return bool(load_auth_prefs().get("phone_access"))
