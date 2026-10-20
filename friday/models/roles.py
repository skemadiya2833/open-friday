"""Role-based model map (installed models only). Defaults unchanged until measured.

Roles:
  fast   — short/urgent replies (defaults to same 9b as main; set FRIDAY_MODEL_FAST to override)
  main   — planning + chat → qwen3.5:9b (current default)
  vision — screen grounding → qwen3-vl:8b-instruct or qwen3.5:9b (measure)
  coder  — on-demand text/tree/code → qwen3-coder:30b (MoE, spills on 16 GB; never co-resident)

Owner preference: keep a single quality model hot (9b). Avoid co-resident 4b+9b.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelRoles:
    fast: str
    main: str
    vision: str
    coder: str
    embed: str
    # When false (default), all product paths keep using the unified MAIN/VISION env models.
    enabled: bool


def get_model_roles() -> ModelRoles:
    from friday.config import resolve_chat_model, resolve_vision_model

    enabled = _roles_enabled()
    # Systems UI / CHAT_MODEL / VISION_MODEL — always the unified baseline.
    chat = resolve_chat_model()
    vision = resolve_vision_model()
    if enabled:
        # Explicit role map may override (fast/main/vision/coder split).
        main = os.getenv("FRIDAY_MODEL_MAIN", "").strip() or chat
        fast = os.getenv("FRIDAY_MODEL_FAST", main).strip() or main
        vision_tag = os.getenv("FRIDAY_MODEL_VISION", "").strip() or vision
    else:
        # Single-model mode: never let a stale FRIDAY_MODEL_MAIN in .env override
        # the Systems picker (that caused gemma↔qwen load/unload thrash).
        main = chat
        # Opt-in complexity routing may still use FAST without enabling full role map.
        fast = os.getenv("FRIDAY_MODEL_FAST", "").strip() or chat
        vision_tag = vision
    return ModelRoles(
        fast=fast,
        main=main,
        vision=vision_tag,
        coder=os.getenv("FRIDAY_MODEL_CODER", "qwen3-coder:30b").strip(),
        embed=os.getenv("EMBED_MODEL", "nomic-embed-text").strip() or "nomic-embed-text",
        enabled=enabled,
    )


def _roles_enabled() -> bool:
    try:
        from friday.runtime.prefs import get as pref

        return bool(pref("model_roles"))
    except Exception:  # noqa: BLE001
        return os.getenv("FRIDAY_MODEL_ROLES", "false").strip().lower() in ("1", "true", "yes", "on")


def model_for(role: str) -> str:
    """Resolve a role name to a model tag (falls back to main when roles disabled)."""
    roles = get_model_roles()
    if not roles.enabled:
        return roles.main
    return {
        "fast": roles.fast,
        "main": roles.main,
        "vision": roles.vision,
        "coder": roles.coder,
        "embed": roles.embed,
    }.get(role, roles.main)


# JSON Schema used for planner / tool decisions (Ollama structured outputs).
PLANNER_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "action": {"type": "string"},
        "text": {"type": "string"},
        "x": {"type": ["number", "null"]},
        "y": {"type": ["number", "null"]},
        "keys": {"type": "array", "items": {"type": "string"}},
        "description": {"type": "string"},
        "observation": {"type": "string"},
        "message": {"type": "string"},
        "completion_evidence": {"type": "string"},
        "needs_knowledge": {"type": "boolean"},
        "knowledge_query": {"type": "string"},
    },
    "required": ["action"],
    "additionalProperties": True,
}

TOOL_CALL_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "tool": {"type": "string"},
        "args": {"type": "object"},
    },
    "required": ["tool"],
    "additionalProperties": False,
}
