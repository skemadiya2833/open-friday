# Copyright 2025 The OpenJarvis Authors
# Licensed under the Apache License, Version 2.0
# Source: open-jarvis/OpenJarvis src/openjarvis/learning/routing/complexity.py
#         (+ heuristic select ideas from learning/routing/router.py)
# Commit: f9e9d5d28d9e58d7fe601c331fc15a02fad32b2c
# Changes for Friday: stdlib only; no OpenJarvis registries/stubs; pair with
# friday.models.roles (fast=4b, main=9b); opt-in via FRIDAY_COMPLEXITY_ROUTING.

"""Heuristic query complexity scoring and simple/hard model role selection."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

_CODE_PATTERNS = re.compile(
    r"```|`[^`]+`|\bdef\s|\bclass\s|\bimport\s|\bfunction\s|\bconst\s|\bvar\s|\blet\s|"
    r"\bif\s*\(|->|=>|\{\s*\}|\bfor\s+\w+\s+in\s|#include|System\.out",
    re.IGNORECASE,
)
_MATH_PATTERNS = re.compile(
    r"\bsolve\b|\bintegral\b|\bequation\b|\bproof\b|\bderivative\b|\bmatrix\b|"
    r"\btheorem\b|\bcalculate\b|\bcompute\b|\bsigma\b|\bsum\b|\blimit\b|\bprobability\b",
    re.IGNORECASE,
)
_REASONING_PATTERNS = re.compile(
    r"\bexplain\b|\banalyze\b|\bcompare\b|\bwhy\b"
    r"|\bstep[- ]by[- ]step\b|\breason\b|\bthink\b"
    r"|\bpros\s+and\s+cons\b|\btrade-?\s*offs?\b|\bevaluate\b",
    re.IGNORECASE,
)
_MULTI_STEP_PATTERNS = re.compile(
    r"\bthen\b.*\bthen\b|\bfirst\b.*\bnext\b|\bstep\s*\d"
    r"|\b(?:and\s+also|additionally|furthermore)\b"
    r"|\b\d+\.\s",
    re.IGNORECASE | re.DOTALL,
)
_CREATIVE_PATTERNS = re.compile(
    r"\bwrite\b.*\b(?:essay|story|article|report|poem)\b"
    r"|\bgenerate\b.*\b(?:code|script|program)\b"
    r"|\bcreate\b|\bdesign\b|\bdraft\b|\bcompose\b",
    re.IGNORECASE,
)

# Low complexity → fast (4b); at/above this → main (9b). Matches OpenJarvis heuristic.
_SIMPLE_THRESHOLD = 0.20


@dataclass(frozen=True)
class ComplexityResult:
    score: float
    tier: str
    signals: dict


def score_complexity(query: str) -> ComplexityResult:
    """Score a query from 0.0 (trivial) to 1.0 (very complex)."""
    signals: dict = {}
    score = 0.0
    length = len(query or "")
    if length < 20:
        length_score = 0.0
    elif length < 100:
        length_score = 0.3
    elif length < 300:
        length_score = 0.6
    elif length < 800:
        length_score = 0.8
    else:
        length_score = 1.0
    signals["length"] = length_score
    score += 0.20 * length_score

    has_code = bool(_CODE_PATTERNS.search(query or ""))
    has_math = bool(_MATH_PATTERNS.search(query or ""))
    domain_score = 0.0
    if has_code:
        domain_score = max(domain_score, 0.7)
    if has_math:
        domain_score = max(domain_score, 0.8)
    if has_code and has_math:
        domain_score = 1.0
    signals["domain"] = domain_score
    signals["has_code"] = has_code
    signals["has_math"] = has_math
    score += 0.25 * domain_score

    has_reasoning = bool(_REASONING_PATTERNS.search(query or ""))
    has_multi_step = bool(_MULTI_STEP_PATTERNS.search(query or ""))
    reasoning_score = 0.0
    if has_reasoning:
        reasoning_score = 0.6
    if has_multi_step:
        reasoning_score = max(reasoning_score, 0.8)
    if has_reasoning and has_multi_step:
        reasoning_score = 1.0
    signals["reasoning"] = reasoning_score
    signals["has_reasoning"] = has_reasoning
    signals["has_multi_step"] = has_multi_step
    score += 0.25 * reasoning_score

    n_questions = (query or "").count("?")
    numbered = len(re.findall(r"^\s*\d+[.)]\s", query or "", re.MULTILINE))
    bulleted = len(re.findall(r"^\s*[-*]\s", query or "", re.MULTILINE))
    multi_part = n_questions + numbered + bulleted
    multi_score = 0.0 if multi_part <= 1 else (0.5 if multi_part <= 3 else 1.0)
    signals["multi_part"] = multi_score
    score += 0.15 * multi_score

    has_creative = bool(_CREATIVE_PATTERNS.search(query or ""))
    creative_score = 0.7 if has_creative else 0.0
    signals["creative"] = creative_score
    signals["has_creative"] = has_creative
    score += 0.15 * creative_score

    score = max(0.0, min(1.0, score))
    if score < 0.15:
        tier = "trivial"
    elif score < 0.30:
        tier = "simple"
    elif score < 0.55:
        tier = "moderate"
    elif score < 0.80:
        tier = "complex"
    else:
        tier = "very_complex"
    return ComplexityResult(score=round(score, 3), tier=tier, signals=signals)


def complexity_routing_enabled() -> bool:
    try:
        from friday.runtime.prefs import get as pref

        return bool(pref("complexity_routing"))
    except Exception:  # noqa: BLE001
        return os.getenv("FRIDAY_COMPLEXITY_ROUTING", "false").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )


def select_chat_role(query: str, *, urgency: float = 0.5) -> str:
    """Return ``fast`` or ``main`` from heuristic rules (no learned router)."""
    result = score_complexity(query)
    if urgency > 0.8:
        return "fast"
    if result.signals.get("has_code"):
        return "main"
    if result.score <= _SIMPLE_THRESHOLD:
        return "fast"
    if result.signals.get("has_math"):
        return "main"
    if result.score >= 0.55 or result.signals.get("has_reasoning"):
        return "main"
    return "main"


def resolve_routed_chat_model(query: str, *, urgency: float = 0.5) -> tuple[str, dict]:
    """Resolve model tag when complexity routing is on; else main/default chat model."""
    from friday.models.roles import get_model_roles, model_for

    roles = get_model_roles()
    meta: dict = {"complexity_routing": False}
    if not complexity_routing_enabled():
        tag = model_for("main") if roles.enabled else roles.main
        return tag, meta
    role = select_chat_role(query, urgency=urgency)
    scored = score_complexity(query)
    tag = model_for(role) if roles.enabled else (roles.fast if role == "fast" else roles.main)
    # Complexity routing may enable 4b even when FRIDAY_MODEL_ROLES is false.
    if not roles.enabled:
        tag = roles.fast if role == "fast" else roles.main
    meta = {
        "complexity_routing": True,
        "role": role,
        "complexity_score": scored.score,
        "complexity_tier": scored.tier,
        "model": tag,
    }
    return tag, meta
