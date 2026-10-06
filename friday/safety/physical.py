"""Optional proof that a human pressed a key or button recently (not synthetic input).

Windows low-level hooks (WH_KEYBOARD_LL / WH_MOUSE_LL) set an "injected" flag on events created by SendInput,
keybd_event, mouse_event and everything built on them (pyautogui, Windows-MCP). Measured on this PC
(docs/research/injected_input_probe.json): all four synthetic paths were flagged injected.

Used to gate approvals: with ``FRIDAY_REQUIRE_PHYSICAL_INPUT=true`` an approval is accepted only if a NON-injected
key-down or mouse-button-down happened within ``window`` seconds. OFF by default because it can lock out legitimate
input that Windows reports as injected (Remote Desktop, touch/pen via some drivers, on-screen keyboard, accessibility
tools), and because a driver-level injector (e.g. a virtual HID device) is not flagged. It raises the bar for an agent
that clicks "Allow"; it is not a proof against malware running as you.
"""

from __future__ import annotations

import ctypes
import os
import sys
import threading
import time
from ctypes import wintypes

LLKHF_INJECTED, LLMHF_INJECTED = 0x10, 0x01
WM_KEYDOWN, WM_SYSKEYDOWN, WM_LBUTTONDOWN, WM_RBUTTONDOWN = 0x100, 0x104, 0x201, 0x204
ULONG_PTR = ctypes.c_size_t


class _KBD(ctypes.Structure):
    _fields_ = [("vk", wintypes.DWORD), ("scan", wintypes.DWORD), ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("extra", ULONG_PTR)]


class _MSL(ctypes.Structure):
    _fields_ = [("pt", wintypes.POINT), ("data", wintypes.DWORD), ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("extra", ULONG_PTR)]


class PhysicalInputMonitor:
    def __init__(self) -> None:
        self.last_physical = 0.0
        self.last_injected = 0.0
        self.last_key: dict | None = None      # most recent key-down: {"t", "injected", "vk"}
        self.physical_count = 0
        self.injected_count = 0
        self.running = False
        self.error = ""
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._tid = 0
        self._keep: list = []

    # -- called by tests and by the hook callbacks
    def record(self, injected: bool, now: float | None = None, vk: int | None = None) -> None:
        now = time.monotonic() if now is None else now
        if vk is not None:
            self.last_key = {"t": now, "injected": injected}     # deliberately no key identity is kept
        if injected:
            self.last_injected, self.injected_count = now, self.injected_count + 1
        else:
            self.last_physical, self.physical_count = now, self.physical_count + 1

    def recent_physical(self, window: float = 3.0, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        return self.last_physical > 0 and (now - self.last_physical) <= window

    def start(self, timeout: float = 3.0) -> bool:
        if sys.platform != "win32":
            self.error = "Windows only"
            return False
        if self._thread and self._thread.is_alive():
            return self.running
        self._ready.clear()
        self._thread = threading.Thread(target=self._loop, name="FridayPhysicalInput", daemon=True)
        self._thread.start()
        self._ready.wait(timeout)
        return self.running

    def stop(self) -> None:
        if self._tid:
            ctypes.windll.user32.PostThreadMessageW(self._tid, 0x12, 0, 0)
        if self._thread:
            self._thread.join(2)
        self.running = False

    def _loop(self) -> None:
        user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
        proc = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
        user32.SetWindowsHookExW.argtypes = [ctypes.c_int, proc, wintypes.HINSTANCE, wintypes.DWORD]
        user32.SetWindowsHookExW.restype = wintypes.HHOOK
        user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
        user32.CallNextHookEx.restype = ctypes.c_ssize_t

        def kb(n, w, l):
            try:
                if n >= 0 and w in (WM_KEYDOWN, WM_SYSKEYDOWN):
                    s = ctypes.cast(l, ctypes.POINTER(_KBD)).contents
                    self.record(bool(s.flags & LLKHF_INJECTED), vk=int(s.vk))
            except Exception:  # noqa: BLE001 - a hook must never raise
                pass
            return user32.CallNextHookEx(None, n, w, l)

        def ms(n, w, l):
            try:
                if n >= 0 and w in (WM_LBUTTONDOWN, WM_RBUTTONDOWN):
                    self.record(bool(ctypes.cast(l, ctypes.POINTER(_MSL)).contents.flags & LLMHF_INJECTED))
            except Exception:  # noqa: BLE001
                pass
            return user32.CallNextHookEx(None, n, w, l)

        kb_p, ms_p = proc(kb), proc(ms)
        self._keep = [kb_p, ms_p]
        self._tid = kernel32.GetCurrentThreadId()
        h1 = user32.SetWindowsHookExW(13, kb_p, None, 0)
        h2 = user32.SetWindowsHookExW(14, ms_p, None, 0)
        self.running = bool(h1 and h2)
        if not self.running:
            self.error = f"SetWindowsHookEx failed ({ctypes.GetLastError()})"
        self._ready.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        for h in (h1, h2):
            if h:
                user32.UnhookWindowsHookEx(h)
        self.running = False


_monitor: PhysicalInputMonitor | None = None
_lock = threading.Lock()


def required() -> bool:
    return os.getenv("FRIDAY_REQUIRE_PHYSICAL_INPUT", "false").strip().lower() in ("1", "true", "yes")


def get_monitor() -> PhysicalInputMonitor:
    global _monitor
    with _lock:
        if _monitor is None:
            _monitor = PhysicalInputMonitor()
        return _monitor


def set_monitor(m: PhysicalInputMonitor | None) -> None:
    global _monitor
    with _lock:
        _monitor = m


def check_physical(window: float = 3.0) -> tuple[bool, str]:
    """(ok, reason). Always ok when the feature is off. Fails CLOSED when on but the hook is not running."""
    if not required():
        return True, ""
    m = get_monitor()
    if not m.running and not m.start():
        return False, f"physical-input check is on but the input hook is unavailable: {m.error}"
    if m.recent_physical(window):
        return True, ""
    return False, "no physical key press or mouse click was detected just before this approval"
