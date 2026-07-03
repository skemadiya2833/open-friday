"""
Persistent on-screen aim cursor for verify-before-click.

States:
  aim     — yellow/orange crosshair (proposed target)
  adjust  — cyan crosshair (correcting)
  confirm — green crosshair (verified, about to click)
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import queue
import threading
from typing import Literal

from PIL import Image, ImageDraw, ImageFont

from config import CLICK_MARKER_ENABLED

from engine.capture import (
    _create_dib_from_pil,
    _update_layered,
    gdi32,
    kernel32,
    user32,
)

AimState = Literal["aim", "adjust", "confirm"]

WS_EX_LAYERED = 0x00080000
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TRANSPARENT = 0x00000020
WS_POPUP = 0x80000000
WS_VISIBLE = 0x10000000
CS_HREDRAW = 0x0002
CS_VREDRAW = 0x0001
IDC_ARROW = 32512
SW_SHOWNOACTIVATE = 4

_MARKER_CLASS = "FridayAimCursor"
_hinstance = kernel32.GetModuleHandleW(None)
_class_registered = False

_STATE_COLORS = {
    "aim": ((255, 200, 48, 230), (255, 120, 48, 200)),
    "adjust": ((96, 220, 255, 230), (48, 160, 255, 200)),
    "confirm": ((72, 255, 120, 230), (32, 200, 80, 200)),
}

_controller: "AimCursorController | None" = None


def _register_class() -> None:
    global _class_registered
    if _class_registered:
        return
    from engine.capture import WNDCLASSEX, _DEFAULT_WNDPROC

    wc = WNDCLASSEX()
    wc.cbSize = ctypes.sizeof(WNDCLASSEX)
    wc.style = CS_HREDRAW | CS_VREDRAW
    wc.lpfnWndProc = ctypes.cast(_DEFAULT_WNDPROC, ctypes.c_void_p)
    wc.hInstance = _hinstance
    wc.hCursor = user32.LoadCursorW(None, wt.LPCWSTR(IDC_ARROW))
    wc.hbrBackground = None
    wc.lpszClassName = _MARKER_CLASS
    if user32.RegisterClassExW(ctypes.byref(wc)):
        _class_registered = True


def _load_font(size: int = 12):
    try:
        return ImageFont.truetype("C:/Windows/Fonts/consola.ttf", size)
    except Exception:
        return ImageFont.load_default()


def _build_cursor_image(
    screen_w: int, screen_h: int, x: int, y: int, state: AimState, label: str,
) -> Image.Image:
    img = Image.new("RGBA", (screen_w, screen_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    color, ring = _STATE_COLORS.get(state, _STATE_COLORS["aim"])
    arm = 40
    draw.line([(x - arm, y), (x + arm, y)], fill=color, width=3)
    draw.line([(x, y - arm), (x, y + arm)], fill=color, width=3)
    r = 24
    draw.ellipse([x - r, y - r, x + r, y + r], outline=ring, width=3)
    draw.ellipse([x - 6, y - 6, x + 6, y + 6], fill=color)

    state_labels = {"aim": "AIM", "adjust": "ADJUST", "confirm": "CLICK"}
    text = f"{state_labels.get(state, 'AIM')} ({x}, {y})"
    if label:
        text += f" — {label[:40]}"
    font = _load_font(11)
    tx = max(8, min(x - 60, screen_w - 240))
    ty = y + r + 6 if y + r + 30 < screen_h else max(8, y - r - 24)
    draw.rectangle([tx - 4, ty - 2, tx + 230, ty + 14], fill=(10, 10, 20, 210))
    draw.text((tx, ty), text, font=font, fill=(255, 255, 255, 255))
    return img


def draw_aim_marker_on_image(
    img: Image.Image,
    x: int,
    y: int,
    *,
    state: AimState = "aim",
    label: str = "",
) -> Image.Image:
    """
    Composite the aim crosshair onto a screen capture at native coordinates.
    Used for VLM verify frames — Win32 layered overlays are often invisible to mss.
    """
    base = img.convert("RGBA")
    marker = _build_cursor_image(base.width, base.height, x, y, state, label)
    return Image.alpha_composite(base, marker).convert("RGB")


class AimCursorController:
    def __init__(self) -> None:
        self._cmd: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._running = False
        self._visible = threading.Event()

    def _ensure_thread(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, name="FridayAimCursor", daemon=True)
        self._thread.start()
        self._visible.wait(timeout=1.0)

    def show(self, x: int, y: int, *, state: AimState = "aim", label: str = "") -> None:
        if not CLICK_MARKER_ENABLED:
            return
        self._ensure_thread()
        self._cmd.put({"op": "show", "x": x, "y": y, "state": state, "label": label})

    def hide(self) -> None:
        if not self._running:
            return
        self._cmd.put({"op": "hide"})

    def shutdown(self) -> None:
        if self._running:
            self._cmd.put({"op": "stop"})
            if self._thread:
                self._thread.join(timeout=1)
        self._running = False

    def _run(self) -> None:
        EX_STYLE = (
            WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW
            | WS_EX_NOACTIVATE | WS_EX_TRANSPARENT
        )
        hwnd = None
        hdc_mem = None
        hbm = None
        screen_w = user32.GetSystemMetrics(0)
        screen_h = user32.GetSystemMetrics(1)

        try:
            _register_class()
            hwnd = user32.CreateWindowExW(
                EX_STYLE, _MARKER_CLASS, "FridayAim",
                WS_POPUP, 0, 0, screen_w, screen_h,
                None, None, _hinstance, None,
            )
            if not hwnd:
                return

            def _paint(x: int, y: int, state: AimState, label: str) -> None:
                nonlocal hdc_mem, hbm
                panel = _build_cursor_image(screen_w, screen_h, x, y, state, label)
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
                    self._visible.set()

            self._visible.set()

            while True:
                try:
                    cmd = self._cmd.get(timeout=0.05)
                except queue.Empty:
                    continue
                op = cmd.get("op")
                if op == "stop":
                    break
                if op == "hide":
                    user32.ShowWindow(hwnd, 0)  # SW_HIDE
                    self._visible.clear()
                elif op == "show":
                    _paint(cmd["x"], cmd["y"], cmd.get("state", "aim"), cmd.get("label", ""))
        finally:
            if hdc_mem:
                gdi32.DeleteDC(hdc_mem)
            if hbm:
                gdi32.DeleteObject(hbm)
            if hwnd:
                user32.DestroyWindow(hwnd)
            self._running = False


def _get_controller() -> AimCursorController:
    global _controller
    if _controller is None:
        _controller = AimCursorController()
    return _controller


def show_aim_cursor(
    x: int, y: int, *, step: dict | None = None, state: AimState = "aim",
) -> None:
    label = ""
    if step:
        label = str(step.get("description") or step.get("action") or "")
    _get_controller().show(x, y, state=state, label=label)


def confirm_click_target(x: int, y: int, *, step: dict | None = None) -> None:
    show_aim_cursor(x, y, step=step, state="confirm")


def hide_aim_cursor() -> None:
    _get_controller().hide()


# Legacy API
def show_click_target(x: int, y: int, step: dict | None = None, **_) -> None:
    show_aim_cursor(x, y, step=step, state="aim")


def dismiss_click_target(**_) -> None:
    hide_aim_cursor()


def log_click_target(step: dict, x: int, y: int) -> None:
    mx, my = step.get("_model_x"), step.get("_model_y")
    act = step.get("action", "?")
    msg = f"[Aim] {act} native=({x}, {y})"
    if mx is not None:
        msg += f" img=({mx}, {my})"
    print(msg)
