"""Human-facing turn debug log — not fed back to the model.

Writes under ``data/debug/turns-YYYY-MM-DD.jsonl`` (``data/`` is gitignored).
"""

from __future__ import annotations

import json
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

_lock = threading.Lock()


def _path() -> Path:
    from friday.config import DATA_DIR

    root = Path(DATA_DIR) / "debug"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"turns-{date.today().isoformat()}.jsonl"


def log_turn(entry: dict[str, Any]) -> None:
    """Append one JSON line describing what Friday thought / routed / said."""
    row = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        **{k: v for k, v in entry.items() if v is not None},
    }
    try:
        line = json.dumps(row, ensure_ascii=False, default=str)
        with _lock:
            with _path().open("a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception as exc:  # noqa: BLE001
        print(f"[DebugLog] write failed: {exc}", flush=True)
