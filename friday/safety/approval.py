"""Central approval service for confirm-tier tool calls.

A caller thread blocks in :meth:`ApprovalService.request` until the owner answers
in the Control Center (``/api/approvals``), the request times out, or it is
cancelled. Timeout, cancellation and "nobody is listening" all resolve to DENY.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from friday.safety.redact import redact


@dataclass
class PendingApproval:
    id: str
    tool: str
    risk: str
    args: Any                       # already redacted
    reason: str
    created: float
    timeout: float
    caller: str = ""
    run_id: str | None = None
    approved: bool | None = None
    resolved_by: str = ""
    _event: threading.Event = field(default_factory=threading.Event, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tool": self.tool,
            "risk": self.risk,
            "args": self.args,
            "reason": self.reason,
            "created": self.created,
            "expires_in": max(0.0, self.created + self.timeout - time.time()),
            "caller": self.caller,
            "run_id": self.run_id,
        }


Listener = Callable[[str, dict[str, Any]], None]


class ApprovalService:
    def __init__(self, default_timeout: float = 120.0) -> None:
        self.default_timeout = default_timeout
        self._lock = threading.Lock()
        self._pending: dict[str, PendingApproval] = {}
        self._listeners: list[Listener] = []
        # Number of UI surfaces that can answer prompts (web tab, tray, ...).
        # With zero responders, requests are denied immediately instead of hanging.
        self._responders = 0
        self._last_touch = 0.0

    # -- responders / listeners -------------------------------------------
    def add_listener(self, fn: Listener) -> None:
        with self._lock:
            self._listeners.append(fn)

    def remove_listener(self, fn: Listener) -> None:
        with self._lock:
            if fn in self._listeners:
                self._listeners.remove(fn)

    def set_responders(self, count: int) -> None:
        with self._lock:
            self._responders = max(0, count)

    def touch(self) -> None:
        """A UI polled for approvals just now: a human is (probably) present."""
        with self._lock:
            self._last_touch = time.time()

    def has_responder(self, window: float = 6.0) -> bool:
        with self._lock:
            return self._responders > 0 or (time.time() - self._last_touch) < window

    def _notify(self, kind: str, payload: dict[str, Any]) -> None:
        with self._lock:
            listeners = list(self._listeners)
        for fn in listeners:
            try:
                fn(kind, payload)
            except Exception:  # noqa: BLE001 - listeners must never break tool calls
                pass

    # -- request / resolve -------------------------------------------------
    def request(
        self,
        *,
        tool: str,
        risk: str,
        args: Any,
        reason: str = "",
        caller: str = "",
        run_id: str | None = None,
        timeout: float | None = None,
        require_responder: bool = True,
    ) -> tuple[bool, str]:
        """Block until resolved. Returns ``(approved, approver)``."""
        if require_responder and not self.has_responder():
            return False, "denied:no-responder"

        item = PendingApproval(
            id=uuid.uuid4().hex[:12],
            tool=tool,
            risk=risk,
            args=redact(args),
            reason=reason,
            created=time.time(),
            timeout=float(self.default_timeout if timeout is None else timeout),
            caller=caller,
            run_id=run_id,
        )
        with self._lock:
            self._pending[item.id] = item
        self._notify("approval_request", item.to_dict())

        got = item._event.wait(item.timeout)
        with self._lock:
            self._pending.pop(item.id, None)
        if not got or item.approved is None:
            self._notify("approval_resolved", {"id": item.id, "approved": False, "by": "timeout"})
            return False, "denied:timeout"
        return bool(item.approved), item.resolved_by or ("user" if item.approved else "denied:user")

    def resolve(self, approval_id: str, approved: bool, who: str = "user") -> bool:
        with self._lock:
            item = self._pending.get(approval_id)
        if item is None:
            return False
        item.approved = bool(approved)
        item.resolved_by = f"user:{who}" if approved else f"denied:user:{who}"
        item._event.set()
        self._notify("approval_resolved", {"id": approval_id, "approved": bool(approved), "by": who})
        return True

    def cancel_all(self, who: str = "cancel") -> int:
        with self._lock:
            items = list(self._pending.values())
        for it in items:
            it.approved = False
            it.resolved_by = f"denied:{who}"
            it._event.set()
        return len(items)

    def list_pending(self) -> list[dict[str, Any]]:
        with self._lock:
            return [p.to_dict() for p in self._pending.values()]


_service: ApprovalService | None = None
_service_lock = threading.Lock()


def get_approval_service() -> ApprovalService:
    global _service
    with _service_lock:
        if _service is None:
            from friday.config import APPROVAL_TIMEOUT_SECONDS

            _service = ApprovalService(APPROVAL_TIMEOUT_SECONDS)
        return _service


def set_approval_service(svc: ApprovalService | None) -> None:
    global _service
    with _service_lock:
        _service = svc
