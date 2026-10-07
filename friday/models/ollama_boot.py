"""Start the local Ollama server if it is not running (once per process, local only)."""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time

import httpx

from friday.config import OLLAMA_HOST

_lock = threading.Lock()
_tried_at = 0.0


def is_up(timeout: float = 1.5) -> bool:
    try:
        return httpx.get(f"{OLLAMA_HOST}/api/tags", timeout=timeout).status_code == 200
    except httpx.HTTPError:
        return False


def ensure_ollama(wait_seconds: float = 20.0) -> bool:
    """True when Ollama answers (starting ``ollama serve`` detached if needed; retried at most every 60 s)."""
    global _tried_at
    if is_up():
        return True
    if os.getenv("FRIDAY_AUTOSTART_OLLAMA", "true").lower() in ("0", "false", "no", "off"):
        return False
    with _lock:
        if is_up():
            return True
        if time.time() - _tried_at < 60:
            return False
        _tried_at = time.time()
        exe = shutil.which("ollama")
        if not exe:
            return False
        print("[Friday] Ollama is not running - starting it.")
        try:
            subprocess.Popen([exe, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,  # noqa: S603
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as exc:
            print(f"[Friday] could not start Ollama: {exc}")
            return False
    end = time.time() + wait_seconds
    while time.time() < end:
        if is_up():
            return True
        time.sleep(0.5)
    return False
