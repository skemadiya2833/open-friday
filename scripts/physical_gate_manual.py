"""Manual + synthetic physical-input gate check for pairing approvals.

What this proves on THIS PC:
- SendInput / keybd_event events are flagged injected and do NOT satisfy the gate.
- A real key press from the owner DOES (interactively).

Windows-MCP clicks were previously measured as injected
(docs/research/injected_input_probe.json). This script re-checks SendInput and
keybd_event without requiring MCP.

If you are on Remote Desktop / some accessibility stacks, Windows may mark your
own keys as injected — you would be locked out. Use the Windows Hello alternative:
  FRIDAY_PAIR_APPROVE=hello
(see docs/PHONE_SETUP.md and friday/safety/physical.py).

Usage:
  friday_env\\Scripts\\python.exe scripts/physical_gate_manual.py
  friday_env\\Scripts\\python.exe scripts/physical_gate_manual.py --auto-only
"""

from __future__ import annotations

import argparse
import ctypes
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT = ROOT / "docs" / "research" / "physical_gate_check.json"


def _sendinput_key(vk: int = 0x41) -> None:
    """Inject a key via SendInput (should be flagged LLKHF_INJECTED)."""
    ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", ctypes.c_ushort),
            ("wScan", ctypes.c_ushort),
            ("dwFlags", ctypes.c_ulong),
            ("time", ctypes.c_ulong),
            ("dwExtraInfo", ULONG_PTR),
        ]

    class INPUT(ctypes.Structure):
        class _U(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT)]

        _anonymous_ = ("u",)
        _fields_ = [("type", ctypes.c_ulong), ("u", _U)]

    user32 = ctypes.windll.user32
    inp = INPUT(type=1)
    inp.ki = KEYBDINPUT(wVk=vk, wScan=0, dwFlags=0, time=0, dwExtraInfo=0)
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
    inp.ki.dwFlags = 2  # KEYUP
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def _keybd_event(vk: int = 0x42) -> None:
    u = ctypes.windll.user32
    u.keybd_event(vk, 0, 0, 0)
    u.keybd_event(vk, 0, 2, 0)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--auto-only", action="store_true",
                    help="Skip waiting for a real key (CI-friendly); still verifies synthetics fail")
    ap.add_argument("--wait", type=float, default=8.0)
    args = ap.parse_args()

    from friday.safety.physical import PhysicalInputMonitor, check_physical, set_monitor
    import os

    os.environ["FRIDAY_REQUIRE_PHYSICAL_INPUT"] = "true"
    mon = PhysicalInputMonitor()
    set_monitor(mon)
    if not mon.start(timeout=5):
        print(f"FAIL: hook did not start: {mon.error}")
        return 2
    time.sleep(0.3)

    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "hook_running": mon.running,
        "synthetic": {},
        "physical": {},
        "rdp_lockout_note": (
            "If Remote Desktop or some accessibility tools mark your keys as injected, "
            "set FRIDAY_PAIR_APPROVE=hello and approve pairing with Windows Hello on the PC "
            "instead of the physical-input gate."
        ),
        "windows_mcp": "UNVERIFIED this run — see docs/research/injected_input_probe.json (prior PASS)",
    }

    # Synthetic SendInput
    before = mon.injected_count
    _sendinput_key()
    time.sleep(0.2)
    ok, why = check_physical(window=3.0)
    report["synthetic"]["sendinput"] = {
        "injected_delta": mon.injected_count - before,
        "check_physical_ok": ok,
        "why": why,
        # Pass when the gate refuses (synthetic must never count as physical).
        "pass": not ok,
    }
    print("SendInput:", report["synthetic"]["sendinput"])

    # Synthetic keybd_event
    before = mon.injected_count
    _keybd_event()
    time.sleep(0.2)
    ok, why = check_physical(window=3.0)
    report["synthetic"]["keybd_event"] = {
        "injected_delta": mon.injected_count - before,
        "check_physical_ok": ok,
        "why": why,
        "pass": (not ok) and mon.injected_count > before,
    }
    print("keybd_event:", report["synthetic"]["keybd_event"])

    if args.auto_only:
        report["physical"] = {"skipped": True, "reason": "--auto-only"}
    else:
        print(f"\n>>> Press any REAL key within {args.wait:.0f}s (not a scripted one)...", flush=True)
        mon.last_physical = 0.0
        deadline = time.time() + args.wait
        while time.time() < deadline:
            if mon.recent_physical(window=args.wait):
                break
            time.sleep(0.05)
        ok, why = check_physical(window=args.wait)
        report["physical"] = {
            "check_physical_ok": ok,
            "why": why,
            "physical_count": mon.physical_count,
            "pass": bool(ok),
        }
        print("Physical:", report["physical"])

    syn_ok = all(v.get("pass") for v in report["synthetic"].values())
    phys_ok = report["physical"].get("skipped") or report["physical"].get("pass")
    report["summary"] = {"synthetic_refused": syn_ok, "physical_accepted": phys_ok,
                         "overall": syn_ok and bool(phys_ok)}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    print(f"Wrote {OUT}")
    mon.stop()
    return 0 if report["summary"]["overall"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
