"""Cancellable / pausable control surface for a running agent session."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

from friday.ui.events import emit


@dataclass
class AgentController:
    """Shared control flags between the GUI thread and the agent worker."""

    cancel_requested: bool = False
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
        emit("control", action="cancel")
        print("[Friday] Cancel requested — aborting in-flight model calls.")

    def pause(self) -> None:
        self._pause_gate.clear()
        emit("control", action="pause")
        emit("status", status="paused")

    def resume(self) -> None:
        self._pause_gate.set()
        emit("control", action="resume")

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
        emit("approval_request", step=step)
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
        emit("approval_resolved", approved=approved)


_active: AgentController | None = None
_active_lock = threading.Lock()


def get_controller() -> AgentController | None:
    with _active_lock:
        return _active


def set_controller(controller: AgentController | None) -> None:
    global _active
    with _active_lock:
        _active = controller


def cancel_active_agent() -> bool:
    """Cancel the currently running agent, if any. Returns True if one was active."""
    ctrl = get_controller()
    if ctrl is None:
        return False
    ctrl.request_cancel()
    return True
