"""Deprecated — use friday.actions.aim_verify."""

from __future__ import annotations

from friday.actions.aim_verify import refine_aim
from friday.types import ActionStep


def refine_step_with_live_verification(step, feed, native_size, image_size):
    action = ActionStep.from_dict(step) if isinstance(step, dict) else step
    refined = refine_aim(action, feed, native_size, image_size)
    return refined.to_dict()
