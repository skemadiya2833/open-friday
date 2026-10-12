"""Cancellable / pausable control surface for a running agent session."""

from __future__ import annotations

import contextvars
import threading
from dataclasses import dataclass, field

from friday.ui.events import current_run_id, emit


@dataclass
class AgentController:
    """Shared control flags between the GUI thread and the agent worker."""

    cancel_requested: bool = False
    run_id: str | None = None
    _pause_gate: threading.Event = field(default_factory=threading.Event)
    _approval_event: threading.Event = field(default_factory=threading.Event)
    _approval_result: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _http_clients: list = field(default_factory=list)

    def __post_init__(self) -> None:
        # Start unpaused.
        self._pause_gate.set()

    def register_http_client(self, client) -> None:
        with self._lock:
            self._http_clients.append(client)

    def unregister_http_client(self, client) -> None:
        with self._lock:
            try:
                self._http_clients.remove(client)
            except ValueError:
                pass

    def _emit(self, event_type: str, **payload) -> None:
        # Tag with this run even when called from another thread (hotkey, HTTP handler).
        token = current_run_id.set(self.run_id) if self.run_id else None
        try:
            emit(event_type, **payload)
        finally:
            if token is not None:
                current_run_id.reset(token)

    def request_cancel(self) -> None:
        with self._lock:
            self.cancel_requested = True
            clients = list(self._http_clients)
        self.resume()  # unblock if paused
        # Unblock any pending approval as rejection
        self.resolve_approval(False)
        # Abort in-flight Ollama streams immediately.
        for client in clients:
            try:
                client.close()
            except Exception:
                pass
        self._emit("control", action="cancel")
        print("[Friday] Cancel requested — aborting in-flight model calls.")

    def pause(self) -> None:
        self._pause_gate.clear()
        self._emit("control", action="pause")
        self._emit("status", status="paused")

    def resume(self) -> None:
        self._pause_gate.set()
        self._emit("control", action="resume")

    @property
    def is_paused(self) -> bool:
        return not self._pause_gate.is_set()

    def wait_if_paused(self) -> None:
        self._pause_gate.wait()

    def should_stop(self) -> bool:
        return self.cancel_requested

    def request_approval(self, step: dict) -> bool:
        """Block until the GUI (or fallback) resolves approval."""
        self._approval_event.clear()
        self._emit("approval_request", step=step)
        # Wait until resolved or cancelled
        while not self._approval_event.wait(timeout=0.25):
            if self.cancel_requested:
                return False
        with self._lock:
            return self._approval_result

    def resolve_approval(self, approved: bool) -> None:
        with self._lock:
            self._approval_result = approved
        self._approval_event.set()
        self._emit("approval_resolved", approved=approved)


_active: AgentController | None = None          # legacy "most recent" fallback
_live: dict[int, AgentController] = {}           # every controller of a running agent
_active_lock = threading.Lock()
# The controller of the run the current thread belongs to (copied into worker threads).
_ctx_controller: contextvars.ContextVar[AgentController | None] = contextvars.ContextVar(
    "friday_controller", default=None
)


def get_controller() -> AgentController | None:
    """Controller of the calling run if inside one, else the most recently set one."""
    ctrl = _ctx_controller.get()
    if ctrl is not None:
        return ctrl
    with _active_lock:
        return _active


def set_controller(controller: AgentController | None) -> None:
    global _active
    with _active_lock:
        _active = controller
        if controller is not None:
            _live[id(controller)] = controller
    if controller is not None:
        _ctx_controller.set(controller)


def release_controller(controller: AgentController) -> None:
    """Forget a finished run's controller (does not touch other runs)."""
    global _active
    with _active_lock:
        _live.pop(id(controller), None)
        if _active is controller:
            _active = None
    if _ctx_controller.get() is controller:
        _ctx_controller.set(None)


def live_controllers() -> list[AgentController]:
    with _active_lock:
        return list(_live.values())


def cancel_all_agents(reason: str = "cancel") -> int:
    """Cancel every running agent (used by the emergency stop). Returns how many."""
    ctrls = live_controllers()
    for c in ctrls:
        c.request_cancel()
    return len(ctrls)


def cancel_active_agent() -> bool:
    """Cancel running agents. Returns True if any was active (legacy API, cancels all)."""
    return cancel_all_agents("api") > 0
