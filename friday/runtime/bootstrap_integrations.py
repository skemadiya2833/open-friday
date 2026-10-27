"""Proactive local tool bootstrap — Cua Driver, etc.

Owner should not have to micromanage installs. When Systems asks for Cua and the
binary is missing, we attempt the official Windows installer once per process.
"""

from __future__ import annotations

import shutil
import subprocess
import threading
from typing import Any

_lock = threading.Lock()
_cua_attempted = False
_status: dict[str, Any] = {"cua": {"present": False, "message": ""}}


def cua_on_path() -> str | None:
    return shutil.which("cua-driver")


def ensure_cua(*, force: bool = False) -> dict[str, Any]:
    """Install Cua Driver if enabled in prefs and missing. Non-blocking safe to call at startup."""
    global _cua_attempted
    from friday.runtime.prefs import get as pref_get

    want = bool(pref_get("cua_enabled"))
    found = cua_on_path()
    if found:
        _status["cua"] = {"present": True, "path": found, "message": "cua-driver on PATH"}
        return dict(_status["cua"])
    if not want and not force:
        _status["cua"] = {"present": False, "message": "cua_enabled off — skipped"}
        return dict(_status["cua"])

    with _lock:
        if _cua_attempted and not force:
            return dict(_status["cua"])
        _cua_attempted = True

    print("[Bootstrap] Cua Driver missing — installing (official installer)…")
    try:
        # Official one-liner from cua.ai docs (Windows PowerShell).
        cmd = (
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            "irm https://cua.ai/driver/install.ps1 | iex",
        )
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300, check=False)
        found2 = cua_on_path()
        if found2:
            msg = f"Installed cua-driver at {found2}"
            print(f"[Bootstrap] {msg}")
            _status["cua"] = {"present": True, "path": found2, "message": msg}
            # Start MCP if prefs want it
            try:
                from friday.mcp_client import get_mcp_manager

                get_mcp_manager().start("cua")
            except Exception as exc:  # noqa: BLE001
                print(f"[Bootstrap] cua MCP start deferred: {exc}")
            return dict(_status["cua"])
        err = (proc.stderr or proc.stdout or "")[-500:]
        msg = f"Cua install finished but cua-driver not on PATH. Output: {err}"
        print(f"[Bootstrap] {msg}")
        _status["cua"] = {"present": False, "message": msg, "exit_code": proc.returncode}
        return dict(_status["cua"])
    except Exception as exc:  # noqa: BLE001
        msg = f"Cua install failed: {type(exc).__name__}: {exc}"
        print(f"[Bootstrap] {msg}")
        _status["cua"] = {"present": False, "message": msg}
        return dict(_status["cua"])


def sync_integrations_background() -> None:
    """Fire-and-forget from app lifespan."""

    def _run() -> None:
        try:
            ensure_cua()
        except Exception as exc:  # noqa: BLE001
            print(f"[Bootstrap] {exc}")

    threading.Thread(target=_run, name="friday-bootstrap", daemon=True).start()


def status() -> dict[str, Any]:
    found = cua_on_path()
    if found:
        _status["cua"] = {"present": True, "path": found, "message": "cua-driver on PATH"}
    return {"cua": dict(_status.get("cua") or {})}
