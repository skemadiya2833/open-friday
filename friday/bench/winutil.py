"""Windows helpers for the benchmark: window enumeration, safe cleanup, UI Automation reads."""

from __future__ import annotations

import ctypes
import os
import subprocess
import time
from ctypes import wintypes
from dataclasses import dataclass

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]

WM_CLOSE = 0x0010
VK_LWIN, VK_D = 0x5B, 0x44


@dataclass(frozen=True)
class Win:
    hwnd: int
    title: str
    cls: str
    pid: int
    exe: str


def _exe_of(pid: int) -> str:
    h = kernel32.OpenProcess(0x1000, False, pid)        # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(520)
        size = wintypes.DWORD(520)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value).lower()
        return ""
    finally:
        kernel32.CloseHandle(h)


def list_windows(visible_only: bool = True) -> list[Win]:
    out: list[Win] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _lp):
        if visible_only and not user32.IsWindowVisible(hwnd):
            return True
        t = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, t, 512)
        c = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, c, 256)
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if t.value or c.value in ("CabinetWClass", "#32770"):
            out.append(Win(int(hwnd), t.value, c.value, int(pid.value), _exe_of(int(pid.value))))
        return True

    user32.EnumWindows(cb, 0)
    return out


def find_windows(title_contains: str = "", cls: str = "", exe: str = "") -> list[Win]:
    res = []
    for w in list_windows():
        if title_contains and title_contains.lower() not in w.title.lower():
            continue
        if cls and w.cls != cls:
            continue
        if exe and w.exe != exe.lower():
            continue
        res.append(w)
    return res


def _key(vk: int, up: bool = False) -> None:
    user32.keybd_event(vk, 0, 2 if up else 0, 0)


def show_desktop() -> None:
    """Win+D toggles 'show desktop': minimizes (or restores) every window."""
    _key(VK_LWIN)
    _key(VK_D)
    _key(VK_D, True)
    _key(VK_LWIN, True)
    time.sleep(0.8)


# Processes that may be killed by name+pid (only if they were not running before the run).
_KILLABLE = {"notepad.exe", "calculatorapp.exe", "systemsettings.exe"}


def close_new_windows(baseline: set[int], baseline_pids: set[int], *, rounds: int = 3) -> list[str]:
    """Close windows that did not exist before the run. Never touches pre-existing ones.

    WM_CLOSE first; processes in _KILLABLE that did not exist before are then killed (this
    dismisses 'save changes?' prompts). explorer.exe and ApplicationFrameHost.exe are never
    killed (shared with the user's session).
    """
    log: list[str] = []
    for _ in range(rounds):
        new = [w for w in list_windows() if w.hwnd not in baseline]
        if not new:
            break
        for w in new:
            user32.PostMessageW(w.hwnd, WM_CLOSE, 0, 0)
            log.append(f"close {w.exe}:{w.title[:40]}")
        time.sleep(1.0)
    for w in list_windows():
        if w.hwnd in baseline or w.pid in baseline_pids:
            continue
        if w.exe in _KILLABLE:
            subprocess.run(["taskkill", "/F", "/PID", str(w.pid)], capture_output=True, check=False)
            log.append(f"kill {w.exe}:{w.pid}")
    return log


# ----------------------------------------------------------------------------- UIA
_uia = None


def _get_uia():
    global _uia
    if _uia is None:
        import comtypes
        import comtypes.client

        comtypes.client.GetModule("UIAutomationCore.dll")
        from comtypes.gen import UIAutomationClient as UIA

        inst = comtypes.CoCreateInstance(
            UIA.CUIAutomation._reg_clsid_, interface=UIA.IUIAutomation, clsctx=comtypes.CLSCTX_INPROC_SERVER
        )
        _uia = (inst, UIA)
    return _uia


def uia_names(hwnd: int, limit: int = 4000) -> list[str]:
    """Names of all descendants of a window (for success checks only; never fed to the agent)."""
    uia, UIA = _get_uia()
    root = uia.ElementFromHandle(hwnd)
    arr = root.FindAll(UIA.TreeScope_Descendants, uia.CreateTrueCondition())
    names = []
    for i in range(min(arr.Length, limit)):
        try:
            n = arr.GetElement(i).CurrentName
        except Exception:  # noqa: BLE001
            continue
        if n:
            names.append(n)
    return names


def uia_by_automation_id(hwnd: int, automation_id: str) -> str | None:
    uia, UIA = _get_uia()
    root = uia.ElementFromHandle(hwnd)
    cond = uia.CreatePropertyCondition(30011, automation_id)   # UIA_AutomationIdPropertyId
    el = root.FindFirst(UIA.TreeScope_Descendants, cond)
    return el.CurrentName if el else None
