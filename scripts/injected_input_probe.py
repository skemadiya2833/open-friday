"""F2 research probe: can a low-level hook tell physical input from synthetic input on THIS machine?

Installs WH_KEYBOARD_LL and WH_MOUSE_LL hooks, then generates harmless synthetic input in several ways and
reports the 'injected' flags the hook sees:
  1. SendInput (what pyautogui / most automation uses)
  2. keybd_event / mouse_event (legacy API)
  3. the real Windows-MCP tools (Move to the current cursor position, Shortcut f15)
Then it waits for PHYSICAL input (--wait seconds): press any key / click once, so the flags of real hardware input
are recorded too. Without that step the 'physical' column stays empty: that part is a manual test.

    python scripts/injected_input_probe.py --wait 10 --out docs/research/injected_input_probe.json
Only F15 key events and a 0-net mouse nudge are generated. Nothing is typed or clicked.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
WH_KEYBOARD_LL, WH_MOUSE_LL = 13, 14
WM_KEYDOWN, WM_SYSKEYDOWN, WM_LBUTTONDOWN, WM_MOUSEMOVE = 0x100, 0x104, 0x201, 0x200
LLKHF_INJECTED, LLKHF_LOWER_IL = 0x10, 0x02
LLMHF_INJECTED, LLMHF_LOWER_IL = 0x01, 0x02
VK_F15 = 0x7E
ULONG_PTR = ctypes.c_size_t


class KBD(ctypes.Structure):
    _fields_ = [("vk", wintypes.DWORD), ("scan", wintypes.DWORD), ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("extra", ULONG_PTR)]


class MSL(ctypes.Structure):
    _fields_ = [("pt", wintypes.POINT), ("data", wintypes.DWORD), ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("extra", ULONG_PTR)]


HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.CallNextHookEx.restype = ctypes.c_ssize_t

events: list[dict] = []
move_counts: dict[tuple, int] = {}
phase = {"name": "idle"}
_ready = threading.Event()
_tid = [0]


def _kb(n, w, l):
    if n >= 0 and w in (WM_KEYDOWN, WM_SYSKEYDOWN):
        s = ctypes.cast(l, ctypes.POINTER(KBD)).contents
        events.append({"phase": phase["name"], "kind": "key", "vk": s.vk, "injected": bool(s.flags & LLKHF_INJECTED),
                       "lower_il": bool(s.flags & LLKHF_LOWER_IL), "extra": int(s.extra)})
    return user32.CallNextHookEx(None, n, w, l)


def _ms(n, w, l):
    if n >= 0 and w in (WM_LBUTTONDOWN, WM_MOUSEMOVE):
        s = ctypes.cast(l, ctypes.POINTER(MSL)).contents
        if w == WM_MOUSEMOVE:      # physical mouse movement floods the log; count only
            k = (phase["name"], bool(s.flags & LLMHF_INJECTED))
            move_counts[k] = move_counts.get(k, 0) + 1
            return user32.CallNextHookEx(None, n, w, l)
        events.append({"phase": phase["name"], "kind": "click" if w == WM_LBUTTONDOWN else "move",
                       "injected": bool(s.flags & LLMHF_INJECTED), "lower_il": bool(s.flags & LLMHF_LOWER_IL),
                       "extra": int(s.extra)})
    return user32.CallNextHookEx(None, n, w, l)


_kb_p, _ms_p = HOOKPROC(_kb), HOOKPROC(_ms)


def _hook_thread():
    _tid[0] = kernel32.GetCurrentThreadId()
    h1 = user32.SetWindowsHookExW(WH_KEYBOARD_LL, _kb_p, None, 0)
    h2 = user32.SetWindowsHookExW(WH_MOUSE_LL, _ms_p, None, 0)
    _ready.set()
    msg = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))
    user32.UnhookWindowsHookEx(h1)
    user32.UnhookWindowsHookEx(h2)


# --- synthetic generators
class KI(ctypes.Structure):
    _fields_ = [("vk", wintypes.WORD), ("scan", wintypes.WORD), ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("extra", ULONG_PTR)]


class MI(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("data", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("extra", ULONG_PTR)]


class _U(ctypes.Union):
    _fields_ = [("ki", KI), ("mi", MI)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


def send_input_key():
    for up in (0, 2):
        i = INPUT(1, _U(ki=KI(VK_F15, 0, up, 0, 0)))
        user32.SendInput(1, ctypes.byref(i), ctypes.sizeof(INPUT))


def send_input_mouse():
    for dx in (1, -1):
        i = INPUT(0, _U(mi=MI(dx, 0, 0, 0x0001, 0, 0)))
        user32.SendInput(1, ctypes.byref(i), ctypes.sizeof(INPUT))


def legacy_key():
    user32.keybd_event(VK_F15, 0, 0, 0)
    user32.keybd_event(VK_F15, 0, 2, 0)


def legacy_mouse():
    user32.mouse_event(0x0001, 1, 0, 0, 0)
    user32.mouse_event(0x0001, -1, 0, 0, 0)


def via_windows_mcp():
    from friday.mcp_client.manager import get_mcp_manager
    from friday.tools.registry import call_tool_result

    m = get_mcp_manager()
    m.start("windows")
    for _ in range(90):
        if any(s.get("name") == "windows" and s.get("status") == "ready" for s in m.status()):
            break
        time.sleep(2)
    pt = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    out = {}
    try:
        phase["name"] = "windows_mcp_move"
        # Move/Shortcut are confirm-tier: use the registry's own approval-free path only through a run grant.
        from friday.safety import grant as GR

        GR.issue("probe", ("windows__",), "injected-input-probe", 120)
        # a scratch Tk window as a harmless click target (our own window, nothing else is clicked)
        import tkinter as tk

        root = tk.Tk()
        root.geometry("200x120+600+400")
        root.attributes("-topmost", True)
        tk.Label(root, text="probe click target").pack(expand=True)
        root.update()
        time.sleep(0.5)
        phase["name"] = "windows_mcp_click"
        r = call_tool_result("windows__Click", {"loc": [700, 460]}, caller="probe", run_id="probe")
        out["click"] = (r.text() or "")[:80]
        root.update()
        time.sleep(0.4)
        root.destroy()
        r = call_tool_result("windows__Move", {"loc": [pt.x, pt.y]}, caller="probe", run_id="probe")
        out["move"] = (r.text() or "")[:80]
        time.sleep(0.3)
        phase["name"] = "windows_mcp_shortcut"
        r = call_tool_result("windows__Shortcut", {"shortcut": "f15"}, caller="probe", run_id="probe")
        out["shortcut"] = (r.text() or "")[:80]
        time.sleep(0.3)
    finally:
        GR.revoke_run("probe")
        m.stop("windows")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait", type=int, default=10, help="seconds to wait for you to press a key / click physically")
    ap.add_argument("--no-mcp", action="store_true")
    ap.add_argument("--out", default=str(ROOT / "docs" / "research" / "injected_input_probe.json"))
    a = ap.parse_args()
    threading.Thread(target=_hook_thread, daemon=True).start()
    _ready.wait(5)
    time.sleep(0.3)
    for name, fn in (("sendinput_key", send_input_key), ("sendinput_mouse", send_input_mouse),
                     ("legacy_key", legacy_key), ("legacy_mouse", legacy_mouse)):
        phase["name"] = name
        fn()
        time.sleep(0.3)
    mcp = {} if a.no_mcp else via_windows_mcp()
    print(f"Now press any key or click once within {a.wait} s (physical input)...", flush=True)
    phase["name"] = "physical"
    time.sleep(a.wait)
    phase["name"] = "done"
    user32.PostThreadMessageW(_tid[0], 0x12, 0, 0)
    summary: dict[str, dict] = {}
    for e in events:
        if e["phase"] in ("idle", "done"):
            continue
        s = summary.setdefault(e["phase"], {"events": 0, "injected": 0, "not_injected": 0})
        s["events"] += 1
        s["injected" if e["injected"] else "not_injected"] += 1
    moves = {f"{p}:{'injected' if inj else 'physical'}": c for (p, inj), c in move_counts.items()}
    res = {"summary": summary, "mouse_move_events": moves, "windows_mcp": mcp, "events": events[:200], "python": sys.version.split()[0]}
    Path(a.out).write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
