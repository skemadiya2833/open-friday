"""Consent-gated foreground window sampling (no screenshots). Off by default."""

from __future__ import annotations

import json
import platform
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from friday.config import DATA_DIR, ensure_data_dirs
from friday.security.content_scan import apply_secrets, Mode

_DEFAULT_INTERVAL = 30.0
_MAX_SAMPLES = 50_000
_RETENTION_DAYS = 14

_EXCLUDE_APP = re.compile(
    r"(1password|lastpass|bitwarden|keepass|dashlane|enpass|keeper|password)",
    re.I,
)
_EXCLUDE_TITLE = re.compile(
    r"(password|banking|sign[\s-]?in|inprivate|incognito|private browsing|"
    r"credit card|ssn|otp|2fa|authenticator)",
    re.I,
)

_thread: threading.Thread | None = None
_stop = threading.Event()


def _consent_path() -> Path:
    ensure_data_dirs()
    return Path(DATA_DIR) / "activity_consent.json"


def _log_path() -> Path:
    ensure_data_dirs()
    return Path(DATA_DIR) / "activity_local.jsonl"


def load_consent() -> dict[str, Any]:
    p = _consent_path()
    if not p.is_file():
        return {"enabled": False, "updated_at": None}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"enabled": False, "updated_at": None}
    return {"enabled": bool(data.get("enabled")), "updated_at": data.get("updated_at")}


def set_consent(enabled: bool) -> dict[str, Any]:
    from friday.atomic import write_text_atomic

    payload = {
        "enabled": bool(enabled),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    write_text_atomic(_consent_path(), json.dumps(payload, indent=2))
    if enabled:
        start_sampler()
    else:
        stop_sampler()
    return load_consent()


def consent_enabled() -> bool:
    return bool(load_consent().get("enabled"))


def _should_exclude(app: str, title: str) -> bool:
    blob = f"{app} {title}"
    if _EXCLUDE_APP.search(app or ""):
        return True
    if _EXCLUDE_TITLE.search(blob):
        return True
    return False


def _redact(text: str) -> str:
    rep = apply_secrets(text or "", mode=Mode.REDACT, audit_tool="activity_local")
    return rep.text or ""


def _foreground_win32() -> tuple[str, str]:
    if platform.system() != "Windows":
        return "", ""
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return "", ""
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        length = user32.GetWindowTextLengthW(hwnd) + 1
        buf = ctypes.create_unicode_buffer(length)
        user32.GetWindowTextW(hwnd, buf, length)
        title = buf.value or ""
        # Process image name via QueryFullProcessImageName if available
        app = ""
        try:
            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
            if h:
                size = wintypes.DWORD(260)
                name_buf = ctypes.create_unicode_buffer(size.value)
                if hasattr(kernel32, "QueryFullProcessImageNameW"):
                    kernel32.QueryFullProcessImageNameW(h, 0, name_buf, ctypes.byref(size))
                    app = Path(name_buf.value).name if name_buf.value else ""
                kernel32.CloseHandle(h)
        except Exception:
            pass
        return app, title
    except Exception:
        return "", ""


def sample_once() -> dict[str, Any] | None:
    if not consent_enabled():
        return None
    app, title = _foreground_win32()
    if not app and not title:
        return None
    if _should_exclude(app, title):
        return None
    app = _redact(app)[:200]
    title = _redact(title)[:500]
    row = {
        "ts": time.time(),
        "app": app,
        "title": title,
        "source": "local",
    }
    _append_sample(row)
    return row


def _append_sample(row: dict[str, Any]) -> None:
    p = _log_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    _enforce_retention()


def _enforce_retention() -> None:
    p = _log_path()
    if not p.is_file():
        return
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except Exception:
        return
    cutoff = time.time() - _RETENTION_DAYS * 86400
    kept: list[str] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
            if float(obj.get("ts") or 0) >= cutoff:
                kept.append(line)
        except Exception:
            continue
    if len(kept) > _MAX_SAMPLES:
        kept = kept[-_MAX_SAMPLES:]
    if len(kept) != len(lines):
        from friday.atomic import write_text_atomic

        write_text_atomic(p, "\n".join(kept) + ("\n" if kept else ""))


def read_samples(*, since: float | None = None, until: float | None = None) -> list[dict[str, Any]]:
    p = _log_path()
    if not p.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
            ts = float(obj.get("ts") or 0)
        except Exception:
            continue
        if since is not None and ts < since:
            continue
        if until is not None and ts > until:
            continue
        out.append(obj)
    return out


def samples_to_events(samples: list[dict[str, Any]], *, gap_seconds: float = 60.0) -> list[dict[str, Any]]:
    """Turn point samples into duration blocks (interval between samples)."""
    if not samples:
        return []
    ordered = sorted(samples, key=lambda s: float(s.get("ts") or 0))
    events: list[dict[str, Any]] = []
    for i, s in enumerate(ordered):
        ts = float(s.get("ts") or 0)
        nxt = float(ordered[i + 1].get("ts") or ts) if i + 1 < len(ordered) else ts + gap_seconds
        dur = max(0.0, min(gap_seconds, nxt - ts))
        events.append(
            {
                "source": "local",
                "start": ts,
                "duration": dur,
                "app": s.get("app") or "",
                "title": s.get("title") or "",
                "category": "uncategorized",
            }
        )
    return events


def delete_all() -> dict[str, Any]:
    stop_sampler()
    removed = {"log": False, "consent": False}
    for p, key in ((_log_path(), "log"), (_consent_path(), "consent")):
        if p.is_file():
            p.unlink()
            removed[key] = True
    return {"deleted": removed}


def _sampler_loop(interval: float) -> None:
    while not _stop.wait(interval):
        try:
            sample_once()
        except Exception:
            pass


def start_sampler(*, interval: float = _DEFAULT_INTERVAL) -> bool:
    global _thread
    if not consent_enabled():
        return False
    if _thread and _thread.is_alive():
        return True
    _stop.clear()
    _thread = threading.Thread(target=_sampler_loop, args=(interval,), name="activity-local", daemon=True)
    _thread.start()
    return True


def stop_sampler() -> None:
    _stop.set()


def status() -> dict[str, Any]:
    c = load_consent()
    p = _log_path()
    count = 0
    if p.is_file():
        count = sum(1 for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip())
    return {
        "consent": c,
        "samples_on_disk": count,
        "sampler_running": bool(_thread and _thread.is_alive()),
        "platform": platform.system(),
    }
