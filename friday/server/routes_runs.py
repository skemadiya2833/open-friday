"""Run management and emergency stop API."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/api")


@router.get("/runs")
def runs_list() -> dict[str, Any]:
    from friday.agent.runs import get_run_manager

    return {"runs": [r.to_dict() for r in get_run_manager().list()]}


@router.get("/runs/{run_id}")
def run_get(run_id: str) -> dict[str, Any]:
    from friday.agent.runs import get_run_manager

    run = get_run_manager().get(run_id)
    if run is None:
        raise HTTPException(404, "Unknown run")
    return run.to_dict()


@router.get("/runs/{run_id}/events")
def run_events(run_id: str, start: int = 0) -> StreamingResponse:
    """Server-sent events for ONE run only. Ends when the run ends."""
    from friday.agent.runs import get_run_manager

    run = get_run_manager().get(run_id)
    if run is None:
        raise HTTPException(404, "Unknown run")

    def gen():
        for ev in run.iter_events(start=max(0, start)):
            yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'type': 'stream_end', 'run_id': run_id})}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-store"})


@router.post("/runs/{run_id}/cancel")
def run_cancel(run_id: str) -> dict[str, Any]:
    from friday.agent.runs import get_run_manager

    if get_run_manager().get(run_id) is None:
        raise HTTPException(404, "Unknown run")
    return {"cancelled": get_run_manager().cancel(run_id)}


@router.get("/estop")
def estop_status() -> dict[str, Any]:
    from friday.safety.estop import get_estop

    e = get_estop()
    return {
        "hotkey": e.hotkey if e else None,
        "armed": bool(e and e.registered),
        "error": e.error if e else "not started",
        "triggers": e.trigger_count if e else 0,
    }


@router.post("/estop")
def estop_trigger() -> dict[str, Any]:
    """Same effect as the hotkey. Always allowed (it only stops things)."""
    from friday.safety.estop import emergency_stop

    return emergency_stop("web-ui").to_dict()
