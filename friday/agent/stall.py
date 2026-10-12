"""No-progress detection, call timeouts and the recovery ladder (Stage K1).

* ``StallDetector`` watches one fingerprint per step (UI tree + foreground window), the action signatures, and the
  wall-clock time spent without any visible progress.
* ``Recovery`` defines the order in which the agent tries to get unstuck:
      re-observe -> Escape -> safe alternative -> vision fallback -> fail with a structured reason.
* ``call_with_timeout`` bounds every MCP and model call. A Python thread cannot be killed, so a timed-out call is
  abandoned (daemon thread) and reported as ``CallTimeout``; the agent treats that as no progress.
* ``hung_windows`` finds "(Not Responding)" windows. The agent never kills anything: it waits a bounded time and
  then fails with reason ``hung_window``.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

RECOVERY_ORDER = ("reobserve", "escape", "alternative", "vision", "fail")
_HUNG = re.compile(r"not responding", re.I)


class CallTimeout(TimeoutError):
    pass


def call_with_timeout(fn: Callable[[], Any], seconds: float | None, what: str = "call") -> Any:
    """Run ``fn`` and give up waiting after ``seconds`` (None/0 = no limit)."""
    if not seconds or seconds <= 0:
        return fn()
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["v"] = fn()
        except BaseException as exc:  # noqa: BLE001 - re-raised in the caller's thread
            box["e"] = exc

    th = threading.Thread(target=run, daemon=True, name=f"timeout-{what}")
    th.start()
    th.join(seconds)
    if th.is_alive():
        raise CallTimeout(f"{what} did not answer within {seconds:g}s")
    if "e" in box:
        raise box["e"]
    return box.get("v")


def native_hung(handle: int) -> bool:
    """Win32 ``IsHungAppWindow``: the UI-Automation tree may still say "Normal" for a frozen window."""
    try:
        import ctypes
        return bool(handle) and bool(ctypes.windll.user32.IsHungAppWindow(int(handle)))
    except Exception:  # noqa: BLE001 - not Windows / bad handle
        return False


def hung_windows(snap: Any, native: bool = True) -> list[str]:
    """Titles (or statuses) of windows reported as not responding (by title, status, or Win32)."""
    out = []
    if native:
        for w in [getattr(snap, "focused", None), *(getattr(snap, "windows", []) or [])]:
            if w is not None and native_hung(getattr(w, "handle", 0)) and w.name not in out:
                out.append(w.name)
    for w in getattr(snap, "windows", []) or []:
        if _HUNG.search(w.name or "") or _HUNG.search(w.status or ""):
            out.append(w.name)
    f = getattr(snap, "focused", None)
    if f is not None and (_HUNG.search(f.name or "") or _HUNG.search(f.status or "")) and f.name not in out:
        out.append(f.name)
    return out


@dataclass
class Stall:
    kind: str            # unchanged_screen | repeated_action | hung_window | time_cap | call_timeout
    detail: str = ""

    def to_dict(self) -> dict:
        return {"kind": self.kind, "detail": self.detail}


@dataclass
class StallDetector:
    max_unchanged: int = 3            # consecutive steps whose screen fingerprint did not change
    max_repeat: int = 6               # identical consecutive actions
    max_wasted_seconds: float = 60.0  # wall-clock time without any progress (a changed fingerprint resets it)
    max_revisits: int = 2             # returns to an already-seen (non-adjacent) screen state = going in circles
    clock: Callable[[], float] = time.monotonic
    _visits: dict = field(default_factory=dict)
    _last_fp: str | None = None
    _unchanged: int = 0
    _last_progress: float = field(default=0.0)
    _sigs: list = field(default_factory=list)

    def __post_init__(self) -> None:
        self._last_progress = self.clock()

    def record(self, fingerprint: str, action_sig: Any = None) -> Stall | None:
        """Call once per step with the post-action fingerprint and the action just taken."""
        now = self.clock()
        if self._last_fp is None or fingerprint != self._last_fp:
            self._unchanged = 0
            self._last_progress = now
            if self._last_fp is not None:
                if fingerprint in self._visits:
                    self._visits[fingerprint] += 1      # came back to a state we already left
                    self._cycle = fingerprint
                else:
                    self._visits[fingerprint] = 0
            else:
                self._visits[fingerprint] = 0
        else:
            self._unchanged += 1
        self._last_fp = fingerprint
        if action_sig is not None:
            self._sigs.append(action_sig)
        return self.check()

    _cycle: str | None = None

    def check(self) -> Stall | None:
        cyc = self._cycle
        self._cycle = None
        if cyc is not None and self._visits.get(cyc, 0) >= self.max_revisits:
            return Stall("state_cycle", f"returned to the same screen state {self._visits[cyc]} times (going in circles)")
        if self._sigs:
            n = 0
            for s in reversed(self._sigs):
                if s != self._sigs[-1]:
                    break
                n += 1
            if n >= self.max_repeat:
                return Stall("repeated_action", f"same action {n} times in a row")
        if self._unchanged >= self.max_unchanged:
            return Stall("unchanged_screen", f"screen unchanged for {self._unchanged} steps")
        waste = self.clock() - self._last_progress
        if waste >= self.max_wasted_seconds:
            return Stall("time_cap", f"{waste:.0f}s without visible progress")
        return None

    def reset_after_recovery(self) -> None:
        self._sigs.clear()
        self._visits.clear()
        self.note_progress()

    def note_progress(self) -> None:
        self._unchanged = 0
        self._last_progress = self.clock()


@dataclass
class Recovery:
    """Walks RECOVERY_ORDER one rung per consecutive stall; ``reset`` after real progress."""
    allow_vision: bool = True
    _i: int = 0
    tried: list[str] = field(default_factory=list)

    def next(self, at_least: str | None = None) -> str:
        if at_least in RECOVERY_ORDER:               # e.g. a state cycle: re-observing / Escape cannot help, change method
            self._i = max(self._i, RECOVERY_ORDER.index(at_least))
        while self._i < len(RECOVERY_ORDER):
            step = RECOVERY_ORDER[self._i]
            self._i += 1
            if step == "vision" and not self.allow_vision:
                continue
            if step != "fail":
                self.tried.append(step)
            return step
        return "fail"

    def reset(self) -> None:
        self._i = 0
        self.tried = []


def failure_reason(stall: Stall | None, tried: list[str], *, elapsed: float, steps: int, extra: str = "") -> dict:
    """Structured reason attached to a failed run (event ``agent_failure`` and the run record)."""
    return {"kind": stall.kind if stall else "unknown", "detail": (stall.detail if stall else extra)[:200],
            "recovery_tried": list(tried), "elapsed_s": round(elapsed, 1), "steps": steps}

