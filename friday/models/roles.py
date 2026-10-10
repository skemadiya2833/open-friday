"""Role-based model map (installed models only). Defaults unchanged until measured.

Roles:
  fast   — routing, greetings, fillers, short answers → qwen3.5:4b
  main   — planning + chat → qwen3.5:9b (current default)
  vision — screen grounding → qwen3-vl:8b-instruct or qwen3.5:9b (measure)
  coder  — on-demand text/tree/code → qwen3-coder:30b (MoE, spills on 16 GB; never co-resident)
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
    return ModelRoles(
        fast=os.getenv("FRIDAY_MODEL_FAST", "qwen3.5:4b").strip(),
        main=os.getenv("FRIDAY_MODEL_MAIN", os.getenv("CHAT_MODEL", "qwen3.5:9b")).strip() or "qwen3.5:9b",
        vision=os.getenv("FRIDAY_MODEL_VISION", os.getenv("VISION_MODEL", "qwen3.5:9b")).strip() or "qwen3.5:9b",
        coder=os.getenv("FRIDAY_MODEL_CODER", "qwen3-coder:30b").strip(),
        embed=os.getenv("EMBED_MODEL", "nomic-embed-text").strip() or "nomic-embed-text",
        enabled=os.getenv("FRIDAY_MODEL_ROLES", "false").strip().lower() in ("1", "true", "yes", "on"),
    )


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
