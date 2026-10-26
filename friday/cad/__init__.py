"""FreeCAD CAD builds via Taiga-S1 (System-1 executor) + Friday as planner."""

from __future__ import annotations

from friday.cad.schema import Goal, GoalFeature, estimate_target, validate_goal
from friday.cad.settings import CadSettings, resolve as resolve_settings
from friday.cad.status import CadStatus, cad_enabled, probe_status

__all__ = [
    "CadSettings",
    "CadStatus",
    "Goal",
    "GoalFeature",
    "cad_enabled",
    "estimate_target",
    "probe_status",
    "resolve_settings",
    "validate_goal",
]
