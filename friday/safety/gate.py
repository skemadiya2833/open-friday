"""Human-in-the-loop safety gate for risky actions."""

from __future__ import annotations

from friday.config import OVERLAY_ENABLED, RISKY_ACTIONS, USE_OVERLAY_APPROVAL
from friday.types import ActionStep
from friday.ui.events import emit


def is_risky(step: ActionStep | dict) -> bool:
    data = step.to_dict() if isinstance(step, ActionStep) else step
    if data.get("risky", False):
        return True
    return str(data.get("action", "")).upper() in RISKY_ACTIONS


def prompt_approval(step: ActionStep | dict) -> bool:
    # Imported lazily to avoid a circular import (agent package ↔ actions package).
    from friday.agent.control import get_controller

    data = step.to_dict() if isinstance(step, ActionStep) else step
    emit("status", status="waiting for approval")

    ctrl = get_controller()
    if ctrl is not None:
        return ctrl.request_approval(data)

    if OVERLAY_ENABLED and USE_OVERLAY_APPROVAL:
        from friday.ui import overlay
        return overlay.await_approval(data)

    print("\n" + "=" * 60)
    print("[SAFETY GATE] Risky action detected. Approval required.")
    print(f"  Action     : {data.get('action')}")
    print(f"  Description: {data.get('description')}")
    print(f"  Coordinates: x={data.get('x')}, y={data.get('y')}")
    print(f"  Text       : {data.get('text')}")
    print("=" * 60)
    response = input("Approve this action? (yes/no): ").strip().lower()
    return response in ("yes", "y")
