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
    # Mirror into the fine-tune corpus when the bubble carries a server turn_id.
    training: dict[str, Any] | None = None
    rid = (body.reply_id or "").strip()
    if rid and not rid.startswith("r-"):
        try:
            from friday.runtime.training_log import rate_turn

            training = rate_turn(
                rid,
                body.vote,  # type: ignore[arg-type]
                note="",
                reply_excerpt=body.text,
            )
        except Exception as exc:  # noqa: BLE001
            training = {"ok": False, "error": str(exc)}
    return {"ok": True, "entry": entry, "training": training}


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
