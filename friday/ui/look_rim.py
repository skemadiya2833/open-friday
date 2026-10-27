"""Orange edge glow on all four screen borders while Friday is looking at the desktop.

Click-through layered window. Hidden during mss capture so the VLM does not see the rim.
Ref-counted: nested observe / agent ticks stay lit until the outer looking session ends.
"""

from __future__ import annotations

import math
import os
import queue
import threading
import time
from typing import Any

from PIL import Image, ImageDraw

from friday.ui.capture import (
    _create_dib_from_pil,
    _update_layered,
    gdi32,
    kernel32,
    user32,
)

WS_EX_LAYERED = 0x00080000
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TRANSPARENT = 0x00000020
WS_POPUP = 0x80000000
CS_HREDRAW = 0x0002
CS_VREDRAW = 0x0001
IDC_ARROW = 32512
SW_SHOWNOACTIVATE = 4

_CLASS = "FridayLookRim"
_hinstance = kernel32.GetModuleHandleW(None)
_class_registered = False
# Keep WNDCLASSEX + class-name pointer alive — GC of these AVs RegisterClassExW on CI.
_wc_keep: Any = None
_class_name_keep: Any = None

# Soft orange — matches HUD "acting" accent.
_ORANGE = (255, 106, 43)
_EDGE_PX = 14

_controller: "LookRimController | None" = None
_lock = threading.RLock()
_looking_depth = 0
_hidden_for_capture = False


def _headless_or_test() -> bool:
    """Win32 layered windows AV / hang on GH runners and under pytest — never create them there."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return True
    if os.environ.get("FRIDAY_HEADLESS", "").strip().lower() in ("1", "true", "yes"):
        return True
    ci = os.environ.get("CI", "").strip().lower()
    if ci in ("1", "true", "yes"):
        return True
    return False


def _enabled() -> bool:
    if _headless_or_test():
        return False
    try:
        from friday.runtime.prefs import get as pref_get

        return bool(pref_get("look_rim"))
    except Exception:  # noqa: BLE001
        return True


def _register_class() -> None:
    global _class_registered, _wc_keep, _class_name_keep
    if _class_registered:
        return
    import ctypes
    import ctypes.wintypes as wt

    from friday.ui.capture import WNDCLASSEX, _DEFAULT_WNDPROC

    wc = WNDCLASSEX()
    wc.cbSize = ctypes.sizeof(WNDCLASSEX)
    wc.style = CS_HREDRAW | CS_VREDRAW
    wc.lpfnWndProc = ctypes.cast(_DEFAULT_WNDPROC, ctypes.c_void_p)
    wc.hInstance = _hinstance
    wc.hCursor = user32.LoadCursorW(None, wt.LPCWSTR(IDC_ARROW))
    wc.hbrBackground = None
    _class_name_keep = ctypes.c_wchar_p(_CLASS)
    wc.lpszClassName = _class_name_keep
    atom = user32.RegisterClassExW(ctypes.byref(wc))
    if atom:
        _wc_keep = wc
        _class_registered = True


def build_rim_image(screen_w: int, screen_h: int, *, pulse: float = 0.0) -> Image.Image:
    """RGBA rim: orange glow fading inward on all four edges."""
    img = Image.new("RGBA", (screen_w, screen_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    edge = max(6, min(_EDGE_PX, screen_w // 40, screen_h // 40))
    # pulse 0..1 boosts outer alpha slightly
    base = 130 + int(50 * (0.5 + 0.5 * math.sin(pulse * math.pi * 2)))
    for i in range(edge):
        t = 1.0 - (i / max(1, edge - 1))
        a = int(base * (t ** 1.4))
        color = (*_ORANGE, max(0, min(255, a)))
        # top
        draw.line([(i, i), (screen_w - 1 - i, i)], fill=color, width=1)
        # bottom
        draw.line([(i, screen_h - 1 - i), (screen_w - 1 - i, screen_h - 1 - i)], fill=color, width=1)
        # left
        draw.line([(i, i), (i, screen_h - 1 - i)], fill=color, width=1)
        # right
        draw.line([(screen_w - 1 - i, i), (screen_w - 1 - i, screen_h - 1 - i)], fill=color, width=1)
    return img


class LookRimController:
    def __init__(self) -> None:
        self._cmd: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._running = False
        self._ready = threading.Event()

    def _ensure(self) -> None:
        if not _enabled():
            return
        if self._running:
            return
        self._running = True
        self._ready.clear()
        self._thread = threading.Thread(target=self._run, name="FridayLookRim", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=1.5)

    def show(self) -> None:
        if not _enabled():
            return
        self._ensure()
        if not self._running:
            return
        self._cmd.put({"op": "show"})

    def hide(self) -> None:
        if not self._running:
            return
        self._cmd.put({"op": "hide"})

    def shutdown(self) -> None:
        if self._running:
            self._cmd.put({"op": "stop"})
            if self._thread:
                self._thread.join(timeout=1.5)
        self._running = False

    def _run(self) -> None:
        # Belt-and-suspenders: never touch Win32 window APIs in CI/pytest.
        if _headless_or_test():
            self._running = False
            self._ready.set()
            return

        EX_STYLE = (
            WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW
            | WS_EX_NOACTIVATE | WS_EX_TRANSPARENT
        )
        hwnd = None
        hdc_mem = None
        hbm = None
        screen_w = user32.GetSystemMetrics(0)
        screen_h = user32.GetSystemMetrics(1)
        visible = False
        t0 = time.time()

        try:
            _register_class()
            if not _class_registered:
                return
            hwnd = user32.CreateWindowExW(
                EX_STYLE, _CLASS, "FridayLookRim",
                WS_POPUP, 0, 0, screen_w, screen_h,
                None, None, _hinstance, None,
            )
            if not hwnd:
                return

            def _paint(pulse: float) -> None:
                nonlocal hdc_mem, hbm
                panel = build_rim_image(screen_w, screen_h, pulse=pulse)
                if hdc_mem:
                    gdi32.DeleteDC(hdc_mem)
                if hbm:
                    gdi32.DeleteObject(hbm)
                hdc_screen = user32.GetDC(None)
                hdc_mem, hbm, w, h = _create_dib_from_pil(hdc_screen, panel)
                user32.ReleaseDC(None, hdc_screen)
                if hdc_mem:
                    user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
                    _update_layered(hwnd, hdc_mem, w, h, 0, 0, alpha=255)

            self._ready.set()

            while True:
                try:
                    cmd = self._cmd.get(timeout=0.05)
                except queue.Empty:
                    cmd = None

                if cmd:
                    op = cmd.get("op")
                    if op == "stop":
                        break
                    if op == "show":
                        visible = True
                        _paint((time.time() - t0) % 1.0)
                    elif op == "hide":
                        visible = False
                        if hwnd:
                            user32.ShowWindow(hwnd, 0)

                if visible and hwnd:
                    # Gentle pulse while looking
                    _paint((time.time() - t0) * 0.55 % 1.0)
        except Exception as exc:  # noqa: BLE001
            print(f"[LookRim] {type(exc).__name__}: {exc}")
        finally:
            if hdc_mem:
                gdi32.DeleteDC(hdc_mem)
            if hbm:
                gdi32.DeleteObject(hbm)
            if hwnd:
                user32.DestroyWindow(hwnd)
            self._ready.set()


def _get() -> LookRimController:
    global _controller
    with _lock:
        if _controller is None:
            _controller = LookRimController()
        return _controller


def begin_looking() -> None:
    """Enter a screen-look session (observe / agent vision). Nested-safe."""
    global _looking_depth
    with _lock:
        _looking_depth += 1
        depth = _looking_depth
        hide_cap = _hidden_for_capture
    if depth == 1 and not hide_cap:
        try:
            _get().show()
        except Exception as exc:  # noqa: BLE001
            print(f"[LookRim] show failed: {exc}")


def end_looking() -> None:
    global _looking_depth
    with _lock:
        _looking_depth = max(0, _looking_depth - 1)
        depth = _looking_depth
    if depth == 0:
        try:
            _get().hide()
        except Exception:  # noqa: BLE001
            pass


def hide_for_capture() -> None:
    """Drop rim for the mss grab so orange edges are not in the VLM frame."""
    global _hidden_for_capture
    with _lock:
        _hidden_for_capture = True
    try:
        _get().hide()
    except Exception:  # noqa: BLE001
        pass


def show_after_capture() -> None:
    global _hidden_for_capture
    with _lock:
        _hidden_for_capture = False
        depth = _looking_depth
    if depth > 0 and _enabled():
        try:
            _get().show()
        except Exception:  # noqa: BLE001
            pass


def status() -> dict[str, Any]:
    with _lock:
        return {
            "looking": _looking_depth > 0,
            "depth": _looking_depth,
            "hidden_for_capture": _hidden_for_capture,
            "enabled": _enabled(),
        }


class looking:
    """Context manager: ``with looking(): …``."""

    def __enter__(self) -> "looking":
        begin_looking()
        return self

    def __exit__(self, *exc: object) -> None:
        end_looking()
