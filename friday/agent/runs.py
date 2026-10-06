"""Run manager: start agent runs without blocking the caller, with per-run events and cancel.

Every run has its own `AgentController`, its own event log and its own thread. Events are
stamped with the run id by `friday.ui.events.emit` (via a ContextVar copied into the worker
thread) and routed to the owning run only, so concurrent sessions cannot see each other's
events. Computer-use runs are *exclusive*: only one may drive the mouse at a time.
"""

from __future__ import annotations

import contextvars
import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

from friday.agent.control import AgentController, release_controller, set_controller
from friday.ui.events import AgentEvent, current_run_id, get_bus

_SKIP_EVENTS = frozenset({"live_frame", "thinking_token", "thinking_clear"})
_DROP_KEYS = frozenset({"image", "frame", "pil_image", "screenshot", "thumb"})
MAX_EVENTS = 2000

Runner = Callable[[str, AgentController], Any]


def jsonable(value: Any) -> Any:
    """Make an event payload JSON-safe; drop image blobs."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if str(k) in _DROP_KEYS:
                continue
            cleaned = jsonable(v)
            if cleaned is not None:
                out[str(k)] = cleaned
        return out
    if "Image" in type(value).__name__:
        return None
    try:
        json.dumps(value)
        return value
    except Exception:  # noqa: BLE001
        return str(value)


class RunBusyError(RuntimeError):
    """An exclusive run is already active."""


@dataclass
class Run:
    id: str
    objective: str
    controller: AgentController
    exclusive: bool
    status: str = "running"            # running | completed | failed | halted | cancelled | ...
    started_at: float = field(default_factory=time.time)
    ended_at: float | None = None
    error: str = ""
    events: list[dict[str, Any]] = field(default_factory=list)
    dropped: int = 0
    _cond: threading.Condition = field(default_factory=threading.Condition)
    _thread: threading.Thread | None = None

    @property
    def done(self) -> bool:
        return self.ended_at is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "objective": self.objective, "status": self.status, "exclusive": self.exclusive,
            "started_at": self.started_at, "ended_at": self.ended_at, "error": self.error,
            "events": len(self.events) + self.dropped, "cancel_requested": self.controller.should_stop(),
        }

    def _append(self, ev: dict[str, Any]) -> None:
        with self._cond:
            self.events.append(ev)
            if len(self.events) > MAX_EVENTS:
                drop = len(self.events) - MAX_EVENTS
                del self.events[:drop]
                self.dropped += drop
            self._cond.notify_all()

    def iter_events(self, start: int = 0, poll: float = 0.25) -> Iterator[dict[str, Any]]:
        """Yield events from absolute index ``start`` until the run is done and drained."""
        idx = start
        while True:
            with self._cond:
                while True:
                    rel = idx - self.dropped
                    if rel < 0:
                        idx, rel = self.dropped, 0
                    if rel < len(self.events):
                        batch = self.events[rel:]
                        break
                    if self.done:
                        return
                    self._cond.wait(poll)
            for ev in batch:
                idx += 1
                yield ev

    def wait(self, timeout: float | None = None) -> bool:
        with self._cond:
            end = None if timeout is None else time.time() + timeout
            while not self.done:
                left = None if end is None else end - time.time()
                if left is not None and left <= 0:
                    return False
                self._cond.wait(0.25 if left is None else min(0.25, left))
        return True


class RunManager:
    def __init__(self) -> None:
        self._runs: dict[str, Run] = {}
        self._lock = threading.RLock()
        self._bus = get_bus()
        self._bus.subscribe_all(self._on_event)

    # -- bus routing -------------------------------------------------------
    def _on_event(self, event: AgentEvent) -> None:
        if event.run_id is None or event.type in _SKIP_EVENTS:
            return
        run = self._runs.get(event.run_id)
        if run is None:
            return
        payload = jsonable(event.payload if isinstance(event.payload, dict) else {})
        run._append({"type": event.type, "run_id": event.run_id, "ts": round(time.time(), 3),
                     "payload": payload if isinstance(payload, dict) else {}})

    def rebind_bus(self) -> None:
        """Re-attach to the current global bus (used by tests after reset_bus())."""
        self._bus = get_bus()
        self._bus.subscribe_all(self._on_event)

    # -- lifecycle ---------------------------------------------------------
    def start(self, objective: str, runner: Runner | None = None, *, exclusive: bool = True) -> Run:
        """Start ``runner(objective, controller)`` on its own thread; returns immediately."""
        if runner is None:
            runner = _default_runner
        with self._lock:
            if exclusive and any(r.exclusive and not r.done for r in self._runs.values()):
                raise RunBusyError("Another desktop run is already active; cancel it first.")
            rid = uuid.uuid4().hex[:12]
            ctrl = AgentController(run_id=rid)
            run = Run(id=rid, objective=objective, controller=ctrl, exclusive=exclusive)
            self._runs[rid] = run
            self._prune()

        ctx = contextvars.copy_context()

        def _body() -> None:
            current_run_id.set(rid)
            set_controller(ctrl)
            from friday.ui.events import emit

            emit("run_start", objective=objective)
            status = "failed"
            try:
                result = runner(objective, ctrl)
                status = getattr(result, "value", None) or (str(result) if result is not None else "completed")
                if ctrl.should_stop() and status not in ("completed",):
                    status = "halted" if status in ("failed", "unknown", "halted") else status
            except Exception as exc:  # noqa: BLE001
                run.error = f"{type(exc).__name__}: {exc}"
                status = "failed"
            finally:
                release_controller(ctrl)
                emit("run_end", status=status)
                with run._cond:
                    run.status = status
                    run.ended_at = time.time()
                    run._cond.notify_all()

        t = threading.Thread(target=lambda: ctx.run(_body), name=f"FridayRun-{rid}", daemon=True)
        run._thread = t
        t.start()
        return run

    def get(self, run_id: str) -> Run | None:
        return self._runs.get(run_id)

    def list(self) -> list[Run]:
        with self._lock:
            return sorted(self._runs.values(), key=lambda r: r.started_at, reverse=True)

    def active(self) -> list[Run]:
        return [r for r in self.list() if not r.done]

    def cancel(self, run_id: str) -> bool:
        run = self._runs.get(run_id)
        if run is None or run.done:
            return False
        run.controller.request_cancel()
        return True

    def cancel_all(self, reason: str = "cancel") -> int:
        n = 0
        for r in self.active():
            r.controller.request_cancel()
            n += 1
        return n

    def _prune(self, keep: int = 50) -> None:
        done = [r for r in self._runs.values() if r.done]
        for r in sorted(done, key=lambda x: x.ended_at or 0)[:-keep] if len(done) > keep else []:
            self._runs.pop(r.id, None)


def _default_runner(objective: str, ctrl: AgentController):
    from friday.agent.loop import run_agent

    return run_agent(objective, controller=ctrl, use_overlay=True)


_manager: RunManager | None = None
_manager_lock = threading.Lock()


def get_run_manager() -> RunManager:
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = RunManager()
        return _manager


def set_run_manager(m: RunManager | None) -> None:
    global _manager
    with _manager_lock:
        _manager = m
