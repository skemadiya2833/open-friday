"""Global emergency stop: a system-wide hotkey that halts every running agent.

Uses Win32 ``RegisterHotKey`` on a dedicated message-loop thread. Unlike a keyboard hook
it needs no elevation, installs no hook into other processes and does not log keys. The
hotkey works while another application has focus, which is the point.

What a trigger does (in order, each step isolated so one failure cannot skip the rest):
1. cancel every live agent controller (also aborts in-flight Ollama streams),
2. cancel every run in the RunManager,
3. deny every pending approval,
4. stop all MCP servers (kill switch),
5. write an audit record.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from dataclasses import dataclass
from typing import Callable

DEFAULT_HOTKEY = "ctrl+alt+f12"

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
WM_HOTKEY, WM_QUIT = 0x0312, 0x0012
_MODS = {"alt": MOD_ALT, "ctrl": MOD_CONTROL, "control": MOD_CONTROL, "shift": MOD_SHIFT, "win": MOD_WIN}
_HOTKEY_ID = 0x4652  # "FR"


def parse_hotkey(spec: str) -> tuple[int, int]:
    """'ctrl+alt+f12' -> (modifiers, virtual-key). Requires at least one modifier."""
    parts = [p.strip().lower() for p in spec.split("+") if p.strip()]
    if len(parts) < 2:
        raise ValueError(f"Hotkey {spec!r} needs at least one modifier and one key")
    mods = 0
    for m in parts[:-1]:
        if m not in _MODS:
            raise ValueError(f"Unknown modifier {m!r} in {spec!r}")
        mods |= _MODS[m]
    key = parts[-1]
    if len(key) == 1 and key.isalnum():
        vk = ord(key.upper())
    elif key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        vk = 0x70 + int(key[1:]) - 1
    else:
        named = {"pause": 0x13, "esc": 0x1B, "escape": 0x1B, "backspace": 0x08, "end": 0x23, "home": 0x24}
        if key not in named:
            raise ValueError(f"Unsupported key {key!r} in {spec!r}")
        vk = named[key]
    return mods, vk


@dataclass
class TriggerReport:
    reason: str
    controllers_cancelled: int = 0
    runs_cancelled: int = 0
    approvals_denied: int = 0
    mcp_servers_stopped: int = 0
    seconds: float = 0.0
    errors: list[str] | None = None

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def emergency_stop(reason: str = "manual", *, stop_mcp: bool = True) -> TriggerReport:
    """Halt everything. Safe to call from any thread, any number of times."""
    t0 = time.time()
    rep = TriggerReport(reason=reason, errors=[])

    def step(label: str, fn: Callable[[], int]) -> int:
        try:
            return int(fn() or 0)
        except Exception as exc:  # noqa: BLE001
            rep.errors.append(f"{label}: {type(exc).__name__}: {exc}")
            return 0

    def _ctrls() -> int:
        from friday.agent.control import cancel_all_agents

        return cancel_all_agents(reason)

    def _runs() -> int:
        from friday.agent.runs import get_run_manager

        return get_run_manager().cancel_all(reason)

    def _approvals() -> int:
        from friday.safety.approval import get_approval_service

        return get_approval_service().cancel_all(f"estop:{reason}")

    def _mcp() -> int:
        from friday.mcp_client.manager import _manager  # only if one was ever created

        return _manager.kill_all() if (stop_mcp and _manager is not None) else 0

    rep.controllers_cancelled = step("controllers", _ctrls)
    rep.runs_cancelled = step("runs", _runs)
    rep.approvals_denied = step("approvals", _approvals)
    rep.mcp_servers_stopped = step("mcp", _mcp)

    def _audit() -> int:
        from friday.safety.audit import get_audit_log

        get_audit_log().record(
            tool="emergency_stop", args={"reason": reason}, outcome="ok", approver=f"hotkey:{reason}",
            risk="safe", caller="estop",
            detail=f"controllers={rep.controllers_cancelled} runs={rep.runs_cancelled} "
                   f"approvals={rep.approvals_denied} mcp={rep.mcp_servers_stopped}",
        )
        return 0

    step("audit", _audit)
    rep.seconds = round(time.time() - t0, 3)
    print(f"[Friday] EMERGENCY STOP ({reason}): {rep.to_dict()}", flush=True)
    return rep


class EmergencyStop:
    """Owns the hotkey thread."""

    def __init__(self, hotkey: str = DEFAULT_HOTKEY, on_trigger: Callable[[str], object] | None = None) -> None:
        self.hotkey = hotkey
        self.on_trigger = on_trigger or (lambda reason: emergency_stop(reason))
        self.registered = False
        self.error = ""
        self.trigger_count = 0
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._tid = 0

    def start(self, timeout: float = 3.0) -> bool:
        if sys.platform != "win32":
            self.error = "hotkey supported on Windows only"
            return False
        if self._thread and self._thread.is_alive():
            return self.registered
        self._ready.clear()
        self._thread = threading.Thread(target=self._loop, name="FridayEStop", daemon=True)
        self._thread.start()
        self._ready.wait(timeout)
        return self.registered

    def stop(self) -> None:
        if self._tid:
            import ctypes

            ctypes.windll.user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
        if self._thread:
            self._thread.join(2)
        self.registered = False

    def _loop(self) -> None:
        import ctypes
        from ctypes import wintypes

        user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
        user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        user32.RegisterHotKey.restype = wintypes.BOOL
        self._tid = kernel32.GetCurrentThreadId()
        try:
            mods, vk = parse_hotkey(self.hotkey)
            if not user32.RegisterHotKey(None, _HOTKEY_ID, mods | MOD_NOREPEAT, vk):
                self.error = f"RegisterHotKey failed (error {ctypes.get_last_error() or kernel32.GetLastError()}); " \
                             f"{self.hotkey} is probably in use by another program"
                return
            self.registered = True
        except Exception as exc:  # noqa: BLE001
            self.error = str(exc)
            return
        finally:
            self._ready.set()

        msg = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY and msg.wParam == _HOTKEY_ID:
                    self.trigger_count += 1
                    try:
                        # Run the stop on its own thread so a slow step never blocks the pump.
                        threading.Thread(target=self.on_trigger, args=("hotkey",), daemon=True).start()
                    except Exception as exc:  # noqa: BLE001
                        print(f"[Friday] estop trigger failed: {exc}")
        finally:
            user32.UnregisterHotKey(None, _HOTKEY_ID)
            self.registered = False


_global: EmergencyStop | None = None
_global_lock = threading.Lock()


def ensure_started() -> EmergencyStop:
    """Start the process-wide hotkey once (idempotent). Disabled by FRIDAY_ESTOP=false."""
    global _global
    with _global_lock:
        if _global is None:
            _global = EmergencyStop(os.getenv("FRIDAY_STOP_HOTKEY", DEFAULT_HOTKEY))
        if os.getenv("FRIDAY_ESTOP", "true").lower() in ("0", "false", "no", "off"):
            return _global
        if not _global.registered:
            ok = _global.start()
            if ok:
                print(f"[Friday] Emergency stop armed: press {_global.hotkey.upper()} to halt the agent.", flush=True)
            else:
                print(f"[Friday] WARNING: emergency stop NOT armed: {_global.error}", flush=True)
        return _global


def get_estop() -> EmergencyStop | None:
    return _global
