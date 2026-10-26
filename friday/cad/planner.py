"""Natural-language idea → Taiga-S1 Goal (Friday is System-2; Taiga is System-1)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from friday.cad.schema import (
    BASE_KINDS,
    GOAL_KINDS,
    Goal,
    GoalFeature,
    estimate_target,
    validate_goal,
)


@dataclass
class PlanResult:
    goal: Goal | None
    summary: str
    clarify: str | None = None
    raw: dict[str, Any] | None = None
    error: str | None = None


_GOAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "clarify": {"type": ["string", "null"]},
        "features": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string"},
                    "params": {"type": "object"},
                },
                "required": ["kind", "params"],
            },
        },
    },
    "required": ["features"],
}


def _heuristic_plan(message: str) -> PlanResult | None:
    """Cheap parse for common plate/cylinder asks when the LLM is unavailable."""
    msg = message.strip()
    # 40x30x10 or 40 × 30 × 10 plate/box
    m = re.search(
        r"(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)",
        msg,
        re.I,
    )
    feats: list[GoalFeature] = []
    if m and re.search(r"\b(plate|box|block|pad|bracket|flange|base)\b", msg, re.I):
        w, d, h = float(m.group(1)), float(m.group(2)), float(m.group(3))
        feats.append(GoalFeature("base_box", {"w": w, "d": d, "h": h}))
    else:
        cyl = re.search(
            r"(?:Ø|diameter|dia\.?)\s*(\d+(?:\.\d+)?).{0,40}(?:h(?:eight)?|thick(?:ness)?)\s*[:=]?\s*(\d+(?:\.\d+)?)"
            r"|(\d+(?:\.\d+)?)\s*(?:mm)?\s*(?:tall|high).{0,20}(?:Ø|dia)",
            msg,
            re.I,
        )
        if cyl and re.search(r"\b(cyl|cylinder|disc|disk|round)\b", msg, re.I):
            if cyl.group(1) and cyl.group(2):
                diam, h = float(cyl.group(1)), float(cyl.group(2))
            else:
                return None
            feats.append(GoalFeature("base_cyl", {"r": diam / 2.0, "h": h}))
    if not feats:
        return None

    hole = re.search(
        r"(?:Ø|diameter|dia\.?)?\s*(\d+(?:\.\d+)?)\s*(?:mm)?\s*holes?"
        r"|holes?\s*(?:of\s*)?(?:Ø|diameter|dia\.?)?\s*(\d+(?:\.\d+)?)",
        msg,
        re.I,
    )
    if hole:
        diam = float(hole.group(1) or hole.group(2))
        feats.append(GoalFeature("hole", {"r": diam / 2.0, "x": 0.0, "y": 0.0}))

    if re.search(r"\bfillet\b", msg, re.I):
        fr = re.search(r"fillet(?:\s*(?:r|radius)\s*[:=]?\s*|\s+)(\d+(?:\.\d+)?)", msg, re.I)
        feats.append(GoalFeature("fillet_top", {"r": float(fr.group(1)) if fr else 1.0}))
    if re.search(r"\bchamfer\b", msg, re.I):
        cs = re.search(r"chamfer(?:\s*(?:size)?\s*[:=]?\s*|\s+)(\d+(?:\.\d+)?)", msg, re.I)
        feats.append(GoalFeature("chamfer_top", {"size": float(cs.group(1)) if cs else 1.0}))

    polar = re.search(r"polar(?:\s*pattern)?\s*[x×]?\s*(\d+)|(\d+)\s*(?:around|radial)", msg, re.I)
    if polar and any(f.kind in ("hole", "hole_std", "pocket_rect", "boss_cyl") for f in feats):
        n = int(polar.group(1) or polar.group(2))
        # Offset the hole so polar makes sense
        for f in feats:
            if f.kind in ("hole", "hole_std") and abs(float(f.params.get("x", 0))) < 1e-6:
                base = feats[0]
                if base.kind == "base_box":
                    f.params["x"] = round(float(base.params["w"]) * 0.3, 1)
                elif "r" in base.params:
                    f.params["x"] = round(float(base.params["r"]) * 0.55, 1)
                break
        feats.append(GoalFeature("polar_pattern", {"n": float(n)}))

    goal = estimate_target(Goal(features=feats, level=len(feats)))
    errs = validate_goal(goal)
    if errs:
        return None
    return PlanResult(goal=goal, summary=goal.summarize(), raw={"source": "heuristic"})


def _coerce_goal(data: dict[str, Any]) -> PlanResult:
    clarify = data.get("clarify")
    if isinstance(clarify, str) and clarify.strip():
        return PlanResult(goal=None, summary="", clarify=clarify.strip(), raw=data)

    feats_raw = data.get("features") or []
    if not isinstance(feats_raw, list) or not feats_raw:
        return PlanResult(
            goal=None,
            summary="",
            clarify="What should I build — base shape and key sizes (mm)?",
            raw=data,
        )

    feats: list[GoalFeature] = []
    for item in feats_raw:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "").strip()
        if kind not in GOAL_KINDS:
            continue
        params_in = item.get("params") or {}
        if not isinstance(params_in, dict):
            params_in = {}
        params: dict[str, float] = {}
        for k, v in params_in.items():
            try:
                params[str(k)] = float(v)
            except (TypeError, ValueError):
                continue
        feats.append(GoalFeature(kind=kind, params=params))

    if not feats or feats[0].kind not in BASE_KINDS:
        return PlanResult(
            goal=None,
            summary="",
            clarify="I need a base shape first (plate, cylinder, hex, or ring) with sizes in mm.",
            raw=data,
        )

    goal = estimate_target(Goal(features=feats, level=len(feats)))
    errs = validate_goal(goal)
    if errs:
        return PlanResult(goal=None, summary="", clarify="; ".join(errs), raw=data, error="; ".join(errs))
    return PlanResult(goal=goal, summary=goal.summarize(), raw=data)


def plan_goal(message: str, *, history: list[dict[str, str]] | None = None) -> PlanResult:
    """Plan a Taiga-S1 goal from the owner's idea. Prefer LLM; fall back to heuristics."""
    from friday.prompts import cad_planner_prompt

    prompt = cad_planner_prompt(message=message.strip(), history=history or [])
    try:
        from friday.models.local import _stream_chat
        from friday.models.manager import get_model_manager

        get_model_manager().ensure_loaded("chat")
        text, _ = _stream_chat(
            [{"role": "user", "content": prompt}],
            format_schema=_GOAL_SCHEMA,
            num_predict=512,
            num_ctx=2048,
        )
        raw = text.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
        data = json.loads(raw)
        if isinstance(data, dict):
            return _coerce_goal(data)
    except Exception:
        pass

    heuristic = _heuristic_plan(message)
    if heuristic is not None:
        return heuristic
    return PlanResult(
        goal=None,
        summary="",
        clarify="Describe the part in mm — for example a 40×30×10 plate with a Ø6 hole and a 1 mm top fillet.",
        error="planner unavailable",
    )
