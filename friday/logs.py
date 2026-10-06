"""Structured logging: one JSON object per line, every record tagged with the current run id.

The run id comes from ``friday.ui.events.current_run_id`` (set by the run manager for each agent run),
so any ``logging`` call made while a run executes is attributable. File: ``<DATA_DIR>/logs/friday.jsonl``
(rotating, 5 x 2 MB). Secrets are passed through ``friday.safety.redact`` before writing.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import time
from pathlib import Path

from friday.ui.events import current_run_id

_configured = False


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        msg = record.getMessage()
        try:
            from friday.safety.redact import redact_text

            msg = redact_text(msg)
        except Exception:  # noqa: BLE001 - logging must never fail
            pass
        rec = {"ts": round(record.created, 3), "t": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(record.created)),
               "level": record.levelname, "logger": record.name, "run_id": current_run_id.get(), "msg": msg}
        if record.exc_info:
            rec["exc"] = self.formatException(record.exc_info).splitlines()[-1]
        return json.dumps(rec, ensure_ascii=False)


def setup_logging(log_dir: str | Path | None = None, level: int = logging.INFO) -> Path:
    global _configured
    if log_dir is None:
        from friday.config import DATA_DIR

        log_dir = Path(DATA_DIR) / "logs"
    path = Path(log_dir)
    path.mkdir(parents=True, exist_ok=True)
    target = path / "friday.jsonl"
    root = logging.getLogger("friday")
    if not _configured:
        h = logging.handlers.RotatingFileHandler(target, maxBytes=2_000_000, backupCount=5, encoding="utf-8")
        h.setFormatter(JsonFormatter())
        root.addHandler(h)
        root.setLevel(level)
        _configured = True
    return target
