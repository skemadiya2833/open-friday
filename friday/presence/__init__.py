"""Presence: skins, model switch, camera presence — architecture over prompt dump."""

from friday.presence.registry import (
    active_skin,
    active_skin_id,
    apply_skin,
    presence_snapshot,
    prompt_presence_block,
)
from friday.presence.skins import (
    CAPABILITY_CLAMP,
    SKINS,
    get_skin,
    list_skins,
    resolve_skin_id,
)

__all__ = [
    "CAPABILITY_CLAMP",
    "SKINS",
    "active_skin",
    "active_skin_id",
    "apply_skin",
    "get_skin",
    "list_skins",
    "presence_snapshot",
    "prompt_presence_block",
    "resolve_skin_id",
]
