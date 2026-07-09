"""Deprecated — use friday.actions.executor."""

from __future__ import annotations

from friday.actions.executor import execute_action
from friday.types import ActionStep, StepResult, VisionPayload


def execute_step(
    step,
    step_index: int = 1,
    total_steps: int = 1,
    session=None,
    feed=None,
    native_size=None,
    image_size=None,
):
    action = ActionStep.from_dict(step) if isinstance(step, dict) else step
    vision = None
    if native_size and image_size:
        vision = VisionPayload(
            native_size=native_size,
            image_size=image_size,
            frame_b64_list=[],
            frame_count=0,
        )
    result = execute_action(
        action,
        session=session,
        feed=feed,
        vision=vision,
        step_index=step_index,
    )
    # Map new results to legacy string values
    mapping = {
        StepResult.CONTINUE: "continue",
        StepResult.REOBSERVE: "screenshot",
        StepResult.SKIPPED: "skipped",
        StepResult.COMPLETE: "complete",
        StepResult.HALT: "halt",
        StepResult.ERROR: "continue",
    }
    return mapping.get(result, "continue")
