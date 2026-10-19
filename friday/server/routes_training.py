"""Fine-tune corpus: day summary + ShareGPT export under ``training/``."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/training", tags=["training"])


def _parse_day(raw: str | None) -> date:
    if not raw:
        return date.today()
    try:
        return datetime.strptime(raw.strip()[:10], "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(400, f"bad date: {raw}") from exc


class RateIn(BaseModel):
    turn_id: str = Field(min_length=1, max_length=64)
    vote: str = Field(pattern="^(up|down|good|bad)$")
    note: str = ""


@router.get("/summary")
def training_summary(day: str | None = Query(None)) -> dict[str, Any]:
    from friday.runtime.training_log import day_summary

    return day_summary(_parse_day(day))


@router.get("/day")
def training_day(
    day: str | None = Query(None),
    labeled_only: bool = Query(False),
) -> dict[str, Any]:
    from friday.runtime.training_log import list_day

    d = _parse_day(day)
    rows = list_day(d)
    if labeled_only:
        rows = [r for r in rows if r.get("label") in {"good", "bad"}]
    return {"date": d.isoformat(), "turns": rows, "count": len(rows)}


@router.post("/export")
def training_export(
    day: str | None = Query(None),
    labeled_only: bool = Query(False),
) -> dict[str, Any]:
    from friday.runtime.training_log import day_summary, export_day

    d = _parse_day(day)
    path = export_day(d, labeled_only=labeled_only)
    return {
        "ok": True,
        "path": str(path),
        "summary": day_summary(d),
        "labeled_only": labeled_only,
    }


@router.post("/rate")
def training_rate(body: RateIn) -> dict[str, Any]:
    from friday.runtime.training_log import rate_turn

    return rate_turn(body.turn_id, body.vote, note=body.note)  # type: ignore[arg-type]
