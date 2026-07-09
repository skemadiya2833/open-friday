"""
Compatibility shim — legacy `from config import ...` still works.

New code should import from `friday.config`.
"""

from friday.config import *  # noqa: F401,F403

# Legacy names expected by older modules / docs
from friday.actions.catalog import ALL_ACTION_NAMES

ALL_ACTIONS = sorted(ALL_ACTION_NAMES)
MAX_STEPS_PER_BATCH = 1
