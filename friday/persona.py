"""Compatibility shim — all prompt text lives in ``friday.prompts``.

Prefer ``from friday.prompts import …`` for new code. This module re-exports
the historical names used across the codebase and docs/PERSONA.md.
"""

from __future__ import annotations

from friday.prompts import (  # noqa: F401
    AGENT as PERSONA_AGENT,
    CHAT as PERSONA_CHAT,
    CORE as PERSONA_CORE,
    DEFAULT_EDGE_VOICE,
    OBSERVE as PERSONA_OBSERVE,
    OBSERVE_VOICE as PERSONA_OBSERVE_VOICE,
    VOICE as PERSONA_VOICE,
)
from friday.prompts import format_persona, owner_name, system_prompt

__all__ = [
    "DEFAULT_EDGE_VOICE",
    "PERSONA_AGENT",
    "PERSONA_CHAT",
    "PERSONA_CORE",
    "PERSONA_OBSERVE",
    "PERSONA_OBSERVE_VOICE",
    "PERSONA_VOICE",
    "format_persona",
    "owner_name",
    "system_prompt",
]
