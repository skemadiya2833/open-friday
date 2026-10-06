"""Append-only, tamper-evident audit log of every tool call.

Format: JSON Lines, one record per line. Each record carries ``prev`` (hash of the
previous line) and ``hash`` (SHA-256 over the canonical record without ``hash``), so
any edit/deletion in the middle of the file is detectable with :func:`verify`.

Honest scope: this is *tamper-evident*, not tamper-proof. Someone with write access
to the file can truncate the tail or rebuild the chain. For stronger guarantees ship
the log to write-once storage.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Iterator

from friday.safety.redact import redact

_GENESIS = "0" * 64


class AuditLog:
    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._last_hash = self._load_last_hash()

    # -- internals ---------------------------------------------------------
    def _load_last_hash(self) -> str:
        if not self.path.exists():
            return _GENESIS
        last = _GENESIS
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    last = json.loads(line).get("hash", last)
                except json.JSONDecodeError:
                    # A torn final line (crash mid-write) must not block new writes.
                    continue
        return last

    @staticmethod
    def _digest(record: dict[str, Any]) -> str:
        body = {k: v for k, v in record.items() if k != "hash"}
        blob = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    # -- API ---------------------------------------------------------------
    def record(
        self,
        *,
        tool: str,
        args: Any,
        outcome: str,
        approver: str,
        risk: str,
        duration_ms: float | None = None,
        result_summary: str = "",
        caller: str = "",
        run_id: str | None = None,
        detail: str = "",
    ) -> dict[str, Any]:
        """Write one record. ``outcome``: ok | error | denied | invalid | unknown_tool."""
        with self._lock:
            rec: dict[str, Any] = {
                "id": uuid.uuid4().hex,
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()) + f".{int((time.time() % 1) * 1000):03d}",
                "tool": tool,
                "risk": risk,
                "caller": caller,
                "run_id": run_id,
                "args": redact(args),
                "outcome": outcome,
                "approver": approver,
                "duration_ms": None if duration_ms is None else round(duration_ms, 1),
                "result": redact(result_summary, max_str=500),
                "detail": redact(detail, max_str=500),
                "prev": self._last_hash,
            }
            rec["hash"] = self._digest(rec)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # A crash mid-write can leave a final line without "\n"; start a fresh line so the
            # new record is not glued to the torn fragment.
            needs_newline = False
            if self.path.exists() and self.path.stat().st_size > 0:
                with self.path.open("rb") as rf:
                    rf.seek(-1, os.SEEK_END)
                    needs_newline = rf.read(1) != b"\n"
            with self.path.open("a", encoding="utf-8") as fh:
                if needs_newline:
                    fh.write("\n")
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            self._last_hash = rec["hash"]
            return rec

    def iter_records(self) -> Iterator[dict[str, Any]]:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        yield {"corrupt": line[:200]}

    def tail(self, n: int = 50) -> list[dict[str, Any]]:
        recs = list(self.iter_records())
        return recs[-n:]

    def verify(self) -> tuple[bool, str]:
        """Check the hash chain. Returns (ok, message)."""
        prev = _GENESIS
        torn = 0
        for i, rec in enumerate(self.iter_records(), start=1):
            if "corrupt" in rec:
                # An unparseable line is not itself proof of tampering (crash mid-write);
                # any removed/replaced *record* still breaks the next record's `prev`.
                torn += 1
                continue
            if rec.get("prev") != prev:
                return False, f"line {i}: chain broken (prev mismatch)"
            if rec.get("hash") != self._digest(rec):
                return False, f"line {i}: record content altered"
            prev = rec["hash"]
        return True, "chain intact" + (f" ({torn} torn line(s) ignored)" if torn else "")


_audit: AuditLog | None = None
_audit_lock = threading.Lock()


def get_audit_log() -> AuditLog:
    global _audit
    with _audit_lock:
        if _audit is None:
            from friday.config import AUDIT_LOG_PATH, ensure_data_dirs

            ensure_data_dirs()
            _audit = AuditLog(AUDIT_LOG_PATH)
        return _audit


def set_audit_log(log: AuditLog | None) -> None:
    """Test hook / reconfiguration."""
    global _audit
    with _audit_lock:
        _audit = log

