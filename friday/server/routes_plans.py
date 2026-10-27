"""Owner API for multi-step plans (approve / versioned rerun)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from friday.plans.store import get_plan_store

router = APIRouter(prefix="/api/plans", tags=["plans"])


class CreatePlan(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    steps: list[str] = Field(default_factory=list)
    kind: str = "generic"
    meta: dict[str, Any] = Field(default_factory=dict)


@router.get("")
def list_plans() -> dict[str, Any]:
    return {"plans": get_plan_store().list()}


@router.post("")
def create_plan(body: CreatePlan) -> dict[str, Any]:
    if not body.steps:
        raise HTTPException(400, "at least one step required")
    return get_plan_store().create(body.title, body.steps, kind=body.kind, meta=body.meta)


@router.get("/{plan_id}")
def get_plan(plan_id: str) -> dict[str, Any]:
    plan = get_plan_store().get(plan_id)
    if not plan:
        raise HTTPException(404, "plan not found")
    return plan


@router.post("/{plan_id}/approve")
def approve_plan(plan_id: str) -> dict[str, Any]:
    try:
        return get_plan_store().approve(plan_id)
    except KeyError:
        raise HTTPException(404, "plan not found") from None
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/{plan_id}/rerun")
def rerun_plan(plan_id: str) -> dict[str, Any]:
    try:
        return get_plan_store().rerun(plan_id)
    except KeyError:
        raise HTTPException(404, "plan not found") from None
