"""Ctrl+C / console close must actually kill Friday.

Default launch parks the main thread in pystray's Windows message loop. That loop
does not run Python signal handlers, so SIGINT never arrives and uvicorn (on a
daemon thread) never hears Ctrl+C. A low-level keyboard hook can also delay the
console event. This module installs a Win32 console handler that force-exits.
"""

from __future__ import annotations

import os
import sys
import threading
from typing import Callable

CTRL_C_EVENT, CTRL_BREAK_EVENT, CTRL_CLOSE_EVENT = 0, 1, 2

_installed = False
_cb_ref = None
_on_stop: Callable[[], None] | None = None
_exit_fn: Callable[[int], None] = os._exit
_lock = threading.Lock()
_stopping = False
_grace_s = 0.4


def reset_for_tests() -> None:
    global _installed, _cb_ref, _on_stop, _exit_fn, _stopping, _grace_s
    _installed = False
    _cb_ref = None
    _on_stop = None
    _exit_fn = os._exit
    _stopping = False
    _grace_s = 0.4


def handle_console_event(ctrl_type: int) -> bool:
    """True if this is a stop signal we own (so the default handler does not prompt Y/N)."""
    if ctrl_type in (CTRL_C_EVENT, CTRL_BREAK_EVENT, CTRL_CLOSE_EVENT):
        request_stop(0)
        return True
    return False


def request_stop(code: int = 0, *, delay: float | None = None) -> None:
    """Stop Friday from any thread. Second Ctrl+C exits immediately."""
    global _stopping
    wait = _grace_s if delay is None else delay
    with _lock:
        already = _stopping
        _stopping = True
    die = _exit_fn
    if already:
        die(code)
        return
    print("\n[Friday] stopping", flush=True)
    cb = _on_stop
    if cb is not None:
        try:
            cb()
        except Exception:  # noqa: BLE001
            pass
    if wait <= 0:
        die(code)
        return
    threading.Timer(wait, lambda: die(code)).start()


def install_ctrl_c(on_stop: Callable[[], None] | None = None, *, exit_fn: Callable[[int], None] | None = None) -> None:
    """Idempotent. Call once from the process that owns the console."""
    global _installed, _cb_ref, _on_stop, _exit_fn
    if on_stop is not None:
        _on_stop = on_stop
    if exit_fn is not None:
        _exit_fn = exit_fn
    if _installed:
        return
    _installed = True
    _bind_console_handler()


def _bind_console_handler() -> None:
    global _cb_ref
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        Handler = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)

        def _handler(ctrl_type: int) -> bool:
            return handle_console_event(int(ctrl_type))

        _cb_ref = Handler(_handler)
        ctypes.windll.kernel32.SetConsoleCtrlHandler(_cb_ref, True)
        return
    import signal

    def _sig(_signum, _frame) -> None:
        request_stop(0)

    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)
