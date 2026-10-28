"""Proactive local tool bootstrap — Cua Driver, Artemis, etc.

Owner should not have to micromanage installs. When Systems asks for Cua and the
binary is missing, we attempt the official Windows installer once per process.
Artemis is cloned into data/vendor/artemis (not shipped in the Friday tree).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

_lock = threading.Lock()
_cua_attempted = False
_artemis_attempted = False
_status: dict[str, Any] = {
    "cua": {"present": False, "message": ""},
    "artemis": {"present": False, "message": ""},
}

_ARTEMIS_REPO = "https://github.com/google/artemis.git"


def cua_on_path() -> str | None:
    return shutil.which("cua-driver")


def artemis_dir() -> Path:
    raw = (os.environ.get("FRIDAY_ARTEMIS_DIR") or "").strip()
    if raw:
        return Path(raw)
    from friday.config import DATA_DIR

    return Path(DATA_DIR) / "vendor" / "artemis"


def artemis_ready() -> bool:
    root = artemis_dir()
    if sys.platform == "win32":
        py = root / ".venv" / "Scripts" / "python.exe"
    else:
        py = root / ".venv" / "bin" / "python"
    return py.is_file() and (root / "mcp_server").is_dir()


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


def ensure_artemis(*, force: bool = False) -> dict[str, Any]:
    """Clone + venv Google Artemis when Systems pref is on."""
    global _artemis_attempted
    from friday.runtime.prefs import get as pref_get

    want = bool(pref_get("artemis_enabled"))
    root = artemis_dir()
    if artemis_ready():
        _status["artemis"] = {
            "present": True,
            "path": str(root),
            "message": "Artemis vendor install ready",
        }
        return dict(_status["artemis"])
    if not want and not force:
        _status["artemis"] = {"present": False, "message": "artemis_enabled off — skipped"}
        return dict(_status["artemis"])

    with _lock:
        if _artemis_attempted and not force:
            return dict(_status["artemis"])
        _artemis_attempted = True

    print(f"[Bootstrap] Artemis — preparing {root}…")
    try:
        root.parent.mkdir(parents=True, exist_ok=True)
        if not (root / ".git").is_dir():
            if root.exists() and any(root.iterdir()):
                msg = f"Artemis path exists but is not a git clone: {root}"
                print(f"[Bootstrap] {msg}")
                _status["artemis"] = {"present": False, "message": msg}
                return dict(_status["artemis"])
            if not shutil.which("git"):
                msg = "git not on PATH — cannot clone Artemis"
                print(f"[Bootstrap] {msg}")
                _status["artemis"] = {"present": False, "message": msg}
                return dict(_status["artemis"])
            print(f"[Bootstrap] Cloning {_ARTEMIS_REPO}…")
            subprocess.run(
                ["git", "clone", "--depth", "1", _ARTEMIS_REPO, str(root)],
                check=True,
                capture_output=True,
                text=True,
                timeout=300,
            )
        py = root / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        if not py.is_file():
            print("[Bootstrap] Creating Artemis venv…")
            # Prefer uv if present (Artemis upstream), else stdlib venv + pip.
            uv = shutil.which("uv")
            if uv:
                subprocess.run(
                    [uv, "sync"],
                    cwd=str(root),
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=600,
                )
            else:
                subprocess.run([sys.executable, "-m", "venv", str(root / ".venv")], check=True, timeout=120)
                pip = [str(py), "-m", "pip", "install", "-U", "pip", "wheel"]
                subprocess.run(pip, check=True, capture_output=True, text=True, timeout=180)
                subprocess.run(
                    [str(py), "-m", "pip", "install", "-e", str(root)],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=600,
                )
        if not artemis_ready():
            msg = "Artemis clone/venv finished but mcp_server / python still missing"
            print(f"[Bootstrap] {msg}")
            _status["artemis"] = {"present": False, "message": msg, "path": str(root)}
            return dict(_status["artemis"])
        msg = f"Artemis ready at {root}"
        print(f"[Bootstrap] {msg}")
        _status["artemis"] = {"present": True, "path": str(root), "message": msg}
        try:
            from friday.mcp_client import get_mcp_manager

            get_mcp_manager().start("artemis")
        except Exception as exc:  # noqa: BLE001
            print(f"[Bootstrap] artemis MCP start deferred: {exc}")
        return dict(_status["artemis"])
    except Exception as exc:  # noqa: BLE001
        msg = f"Artemis setup failed: {type(exc).__name__}: {exc}"
        print(f"[Bootstrap] {msg}")
        _status["artemis"] = {"present": False, "message": msg}
        return dict(_status["artemis"])


def sync_integrations_background() -> None:
    """Fire-and-forget from app lifespan."""

    def _run() -> None:
        try:
            ensure_cua()
        except Exception as exc:  # noqa: BLE001
            print(f"[Bootstrap] {exc}")
        try:
            ensure_artemis()
        except Exception as exc:  # noqa: BLE001
            print(f"[Bootstrap] {exc}")

    threading.Thread(target=_run, name="friday-bootstrap", daemon=True).start()


def status() -> dict[str, Any]:
    found = cua_on_path()
    if found:
        _status["cua"] = {"present": True, "path": found, "message": "cua-driver on PATH"}
    if artemis_ready():
        _status["artemis"] = {
            "present": True,
            "path": str(artemis_dir()),
            "message": "Artemis vendor install ready",
        }
    return {
        "cua": dict(_status.get("cua") or {}),
        "artemis": dict(_status.get("artemis") or {}),
    }
