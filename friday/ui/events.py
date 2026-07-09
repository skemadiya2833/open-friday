"""Process-wide event bus for GUI ↔ agent communication."""

from __future__ import annotations

import threading
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable


Listener = Callable[["AgentEvent"], None]


@dataclass(frozen=True)
class AgentEvent:
    type: str
    payload: dict[str, Any] = field(default_factory=dict)


class EventBus:
    """Thread-safe pub/sub used by the agent loop and GUI."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._listeners: dict[str, list[Listener]] = defaultdict(list)
        self._any: list[Listener] = []

    def subscribe(self, event_type: str, listener: Listener) -> None:
        with self._lock:
            self._listeners[event_type].append(listener)

    def subscribe_all(self, listener: Listener) -> None:
        with self._lock:
            self._any.append(listener)

    def unsubscribe(self, event_type: str, listener: Listener) -> None:
        with self._lock:
            listeners = self._listeners.get(event_type, [])
            if listener in listeners:
                listeners.remove(listener)

    def emit(self, event_type: str, **payload: Any) -> None:
        event = AgentEvent(type=event_type, payload=payload)
        with self._lock:
            targets = list(self._listeners.get(event_type, []))
            targets.extend(self._any)
        for listener in targets:
            try:
                listener(event)
            except Exception as exc:
                print(f"[Events] Listener error ({event_type}): {exc}")


_bus: EventBus | None = None
_bus_lock = threading.Lock()


def get_bus() -> EventBus:
    global _bus
    with _bus_lock:
        if _bus is None:
            _bus = EventBus()
        return _bus


def emit(event_type: str, **payload: Any) -> None:
    get_bus().emit(event_type, **payload)


def reset_bus() -> None:
    global _bus
    with _bus_lock:
        _bus = EventBus()
