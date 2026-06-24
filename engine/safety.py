from config import RISKY_ACTIONS, OVERLAY_ENABLED, USE_OVERLAY_APPROVAL


def is_risky_step(step: dict) -> bool:
    """Returns True if the step is flagged risky or matches known risky actions."""
    if step.get("risky", False):
        return True
    if step.get("action", "").upper() in RISKY_ACTIONS:
        return True
    return False


def prompt_user_approval(step: dict) -> bool:
    """
    Blocks execution and asks the operator for explicit approval.
    Returns True if approved, False if rejected.
    """
    if OVERLAY_ENABLED and USE_OVERLAY_APPROVAL:
        from engine.overlay import await_approval

        return await_approval(step)

    print("\n" + "=" * 60)
    print("[SAFETY GATE] Risky action detected. Approval required.")
    print(f"  Action     : {step.get('action')}")
    print(f"  Description: {step.get('description')}")
    print(f"  Coordinates: x={step.get('x')}, y={step.get('y')}")
    print(f"  Text       : {step.get('text')}")
    print("=" * 60)

    response = input("Approve this action? (yes/no): ").strip().lower()
    return response in ("yes", "y")