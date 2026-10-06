"""Owner-facing API for agentskills.io skills (list, import, review, approve, reject, remove)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from friday.skills.agentskills import SkillError, get_store

router = APIRouter(prefix="/api/skillmd")


class Name(BaseModel):
    name: str
    expected_hash: str | None = None


def _require_ui(request: Request) -> None:
    """Same bar as granting a tool approval: a same-origin browser request from the Friday page."""
    if not request.headers.get("origin") or request.headers.get("sec-fetch-site") != "same-origin":
        raise HTTPException(403, "This action can only be taken from the Friday UI page")


@router.get("")
def list_skills() -> dict[str, Any]:
    s = get_store()
    return {"skills": [m.public() for m in s.list_all()], "pending": s.pending(), "inbox": str(s.inbox)}


@router.post("/import")
def import_skill(body: Name, request: Request) -> dict[str, Any]:
    _require_ui(request)
    try:
        return {"quarantined": True, "review": get_store().import_from_inbox(body.name)}
    except SkillError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/approve")
def approve(body: Name, request: Request) -> dict[str, Any]:
    _require_ui(request)
    try:
        return {"approved": get_store().approve(body.name, "owner:control-center", expected_hash=body.expected_hash)}
    except SkillError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/reject")
def reject(body: Name) -> dict[str, Any]:           # rejecting is always safe
    return {"rejected": get_store().reject(body.name)}


@router.post("/remove")
def remove(body: Name) -> dict[str, Any]:
    return {"removed": get_store().remove(body.name)}
