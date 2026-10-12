"""Research report API — view for chat role; run web research requires tools role."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/reports", tags=["reports"])


def _role(request: Request) -> str:
    sess = getattr(request.state, "session", None) or {}
    return str(sess.get("role") or "chat")


def _require_tools(request: Request) -> None:
    from friday.auth.roles import role_at_least
    from friday.config import FRIDAY_AUTH

    if FRIDAY_AUTH in ("off", ""):
        return
    if not role_at_least(_role(request), "tools"):
        raise HTTPException(403, "Running web research requires the tools role")


class StartBody(BaseModel):
    query: str = Field(..., min_length=2, max_length=2000)
    mode: str = "quick"


class DigBody(BaseModel):
    finding_id: str


@router.get("")
def reports_list() -> list[dict[str, Any]]:
    from friday.reports.store import list_reports

    return list_reports()


@router.get("/{report_id}")
def reports_get(report_id: str) -> dict[str, Any]:
    from friday.reports.store import get_report

    doc = get_report(report_id)
    if not doc:
        raise HTTPException(404, "Not found")
    return doc


@router.delete("/{report_id}")
def reports_delete(report_id: str) -> dict[str, Any]:
    from friday.reports.store import delete_report

    if not delete_report(report_id):
        raise HTTPException(404, "Not found")
    return {"deleted": True}


@router.get("/{report_id}/export.md", response_class=PlainTextResponse)
def reports_export_md(report_id: str) -> str:
    from friday.reports.store import export_markdown, get_report

    doc = get_report(report_id)
    if not doc:
        raise HTTPException(404, "Not found")
    return export_markdown(doc)


@router.get("/{report_id}/export.html", response_class=HTMLResponse)
def reports_export_html(report_id: str) -> str:
    from friday.reports.store import export_standalone_html, get_report

    doc = get_report(report_id)
    if not doc:
        raise HTTPException(404, "Not found")
    return export_standalone_html(doc)


@router.post("/start")
def reports_start(body: StartBody, request: Request) -> dict[str, Any]:
    _require_tools(request)
    from friday.agent.runs import RunBusyError, get_run_manager
    from friday.reports.pipeline import run_research_report

    query = body.query.strip()
    mode = body.mode if body.mode in ("quick", "deep", "think") else "quick"
    holder: dict[str, Any] = {}

    def runner(objective: str, ctrl) -> str:
        def _emit(typ: str, payload: dict | None = None, **kw: Any) -> None:
            from friday.ui.events import emit

            data = dict(payload or {})
            data.update(kw)
            emit(f"report_{typ}", **data)

        doc = run_research_report(objective, mode=mode, emit=_emit)
        holder["report_id"] = doc.get("id")
        return "completed" if not doc.get("fallback_plain") else "completed_fallback"

    try:
        run = get_run_manager().start(query, runner=runner, exclusive=False)
    except RunBusyError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"run_id": run.id, "mode": mode}


@router.post("/{report_id}/dig")
def reports_dig(report_id: str, body: DigBody, request: Request) -> dict[str, Any]:
    _require_tools(request)
    from friday.reports.pipeline import dig_deeper

    try:
        return dig_deeper(report_id, body.finding_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/{report_id}/remember")
def reports_remember(report_id: str) -> dict[str, Any]:
    """Owner-clicked only — store findings to memory."""
    from friday.reports.store import get_report

    doc = get_report(report_id)
    if not doc:
        raise HTTPException(404, "Not found")
    from friday.memory import get_memory

    text = (doc.get("summary") or {}).get("tldr") or ""
    findings = "; ".join(f.get("title") or "" for f in (doc.get("findings") or [])[:6])
    note = f"Research ({doc.get('query')}): {text} Findings: {findings}"
    get_memory().add(note[:2000], metadata={"kind": "research_report", "report_id": report_id})
    return {"ok": True}
