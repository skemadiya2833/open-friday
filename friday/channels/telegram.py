"""Optional Telegram Bot API long-poll channel (ZYRON-inspired; Friday-native).

Token and allow-list live in Systems prefs (secret-masked). Off by default.
Passkey phone Control Center remains the primary remote path — see docs/PHONE_SETUP.md.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import httpx

log = logging.getLogger("friday.channels.telegram")

_API = "https://api.telegram.org"
_lock = threading.RLock()
_thread: threading.Thread | None = None
_stop = threading.Event()
_offset = 0
_status: dict[str, Any] = {"running": False, "error": "", "updates": 0}


def status() -> dict[str, Any]:
    with _lock:
        return dict(_status)


def _token() -> str:
    from friday.runtime.prefs import get

    return str(get("telegram_bot_token") or "").strip()


def _enabled() -> bool:
    from friday.runtime.prefs import get

    return bool(get("telegram_enabled")) and bool(_token())


def _allowed_ids() -> set[str]:
    from friday.runtime.prefs import get

    raw = str(get("telegram_allowed_chat_ids") or "")
    return {p.strip() for p in raw.split(",") if p.strip()}


def _api(token: str, method: str, **params: Any) -> dict[str, Any]:
    url = f"{_API}/bot{token}/{method}"
    with httpx.Client(timeout=httpx.Timeout(35.0, connect=10.0)) as client:
        r = client.post(url, json=params)
        r.raise_for_status()
        data = r.json()
    if not data.get("ok"):
        raise RuntimeError(str(data.get("description") or "telegram api error"))
    return data.get("result")  # type: ignore[return-value]


def send_message(chat_id: int | str, text: str) -> None:
    token = _token()
    if not token:
        return
    # Telegram message limit ~4096
    chunk = (text or "").strip() or "(empty reply)"
    for i in range(0, len(chunk), 3500):
        _api(token, "sendMessage", chat_id=chat_id, text=chunk[i : i + 3500])


def _handle_text(chat_id: int, text: str) -> None:
    from friday.assistant.orchestrator import handle_message

    reply = handle_message(text, session_id=f"telegram:{chat_id}")
    if isinstance(reply, dict):
        out = str(
            reply.get("reply")
            or reply.get("text")
            or reply.get("message")
            or reply.get("content")
            or ""
        )
        if not out:
            # Common orchestrator shape: final spoken / assistant field
            out = str(reply.get("assistant") or reply.get("final") or "")
        if not out:
            out = str(reply)[:2000]
    else:
        out = str(reply)
    send_message(chat_id, out)


def _loop() -> None:
    global _offset
    with _lock:
        _status.update({"running": True, "error": ""})
    log.info("Telegram channel started")
    while not _stop.is_set():
        token = _token()
        if not token or not _enabled():
            break
        try:
            updates = _api(
                token,
                "getUpdates",
                offset=_offset,
                timeout=25,
                allowed_updates=["message"],
            )
            allowed = _allowed_ids()
            for u in updates or []:
                _offset = max(_offset, int(u.get("update_id", 0)) + 1)
                with _lock:
                    _status["updates"] = int(_status.get("updates") or 0) + 1
                msg = u.get("message") or {}
                chat = msg.get("chat") or {}
                chat_id = chat.get("id")
                text = (msg.get("text") or "").strip()
                if chat_id is None or not text:
                    continue
                if str(chat_id) not in allowed:
                    send_message(chat_id, "Friday: this chat is not on the allow-list (Systems → Telegram allowed chat IDs).")
                    continue
                try:
                    _handle_text(int(chat_id), text)
                except Exception as exc:  # noqa: BLE001
                    log.exception("telegram handle failed")
                    try:
                        send_message(chat_id, f"Friday error: {type(exc).__name__}")
                    except Exception:  # noqa: BLE001
                        pass
        except Exception as exc:  # noqa: BLE001
            with _lock:
                _status["error"] = f"{type(exc).__name__}: {exc}"
            time.sleep(3.0)
    with _lock:
        _status["running"] = False
    log.info("Telegram channel stopped")


def start() -> bool:
    """Start long-poll thread if enabled+token. Returns True if running/started."""
    global _thread
    if not _enabled():
        return False
    with _lock:
        if _thread is not None and _thread.is_alive():
            return True
        _stop.clear()
        _thread = threading.Thread(target=_loop, name="friday-telegram", daemon=True)
        _thread.start()
    return True


def stop() -> None:
    global _thread
    _stop.set()
    t = _thread
    if t is not None and t.is_alive():
        t.join(timeout=2.0)
    with _lock:
        _thread = None
        _status["running"] = False


def sync_from_prefs() -> dict[str, Any]:
    """Start or stop to match Systems prefs."""
    if _enabled():
        start()
    else:
        stop()
    return status()
