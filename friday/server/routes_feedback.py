"""Owner thumbs feedback for replies / quips (local, bounded, deletable)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/feedback", tags=["feedback"])


class FeedbackIn(BaseModel):
    vote: str = Field(pattern="^(up|down)$")
    kind: str = "reply"
    text: str = ""
    reply_id: str = ""


@router.post("")
def add_feedback(body: FeedbackIn) -> dict[str, Any]:
    from friday.humor import feedback_store

    entry = feedback_store().add(
        kind=body.kind,
        vote=body.vote,
        text=body.text,
        reply_id=body.reply_id,
    )
    return {"ok": True, "entry": entry}


@router.get("")
def list_feedback(limit: int = 50) -> dict[str, Any]:
    from friday.humor import feedback_store

    return {"entries": feedback_store().list(limit=max(1, min(limit, 200)))}


@router.delete("")
def clear_feedback() -> dict[str, Any]:
    from friday.humor import feedback_store

    n = feedback_store().clear()
    return {"cleared": n}


@router.delete("/{entry_id}")
def delete_feedback(entry_id: str) -> dict[str, Any]:
    from friday.humor import feedback_store

    if not feedback_store().delete(entry_id):
        raise HTTPException(404, "not found")
    return {"deleted": entry_id}
