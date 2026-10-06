"""Control Center API: tools, MCP servers, approvals, audit."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api")


class ApprovalAnswer(BaseModel):
    approved: bool


@router.get("/tools")
def tools_list() -> dict[str, Any]:
    from friday.tools.registry import get_registry

    reg = get_registry()
    return {"version": reg.version, "tools": [t.to_public() for t in reg.list()]}


@router.get("/policy")
def policy_summary() -> dict[str, Any]:
    from friday.config import SHELL_TOOLS_ENABLED
    from friday.safety.policy import get_policy

    p = get_policy()
    return {
        "tiers": p.tiers,
        "tools": p.tools,
        "shell": {"enabled": bool(SHELL_TOOLS_ENABLED), "mode": p.shell.mode,
                  "timeout_seconds": p.shell.timeout_seconds, "allowlist_entries": len(p.shell.allowlist)},
    }


@router.get("/mcp/servers")
def mcp_servers() -> dict[str, Any]:
    from friday.mcp_client import get_mcp_manager

    m = get_mcp_manager()
    return {"config_error": m.config_error, "servers": m.status()}


@router.post("/mcp/servers/{name}/start")
def mcp_start(name: str) -> dict[str, Any]:
    from friday.mcp_client import get_mcp_manager

    try:
        get_mcp_manager().start(name)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"started": name}


@router.post("/mcp/servers/{name}/stop")
def mcp_stop(name: str) -> dict[str, Any]:
    from friday.mcp_client import get_mcp_manager

    get_mcp_manager().stop(name)
    return {"stopped": name}


@router.post("/mcp/kill")
def mcp_kill() -> dict[str, Any]:
    """Kill switch: stop every MCP server, drop their tools, deny pending approvals."""
    from friday.mcp_client import get_mcp_manager
    from friday.safety.approval import get_approval_service

    n = get_mcp_manager().kill_all()
    denied = get_approval_service().cancel_all("kill-switch")
    return {"servers_stopped": n, "approvals_denied": denied}


@router.post("/mcp/reload")
def mcp_reload() -> dict[str, Any]:
    from friday.mcp_client import get_mcp_manager

    m = get_mcp_manager()
    m.reload_config()
    return {"config_error": m.config_error, "servers": [s["name"] for s in m.status()]}


@router.get("/approvals")
def approvals_pending() -> dict[str, Any]:
    """Polled by the Control Center; polling also tells the service a human is present."""
    from friday.safety.approval import get_approval_service

    svc = get_approval_service()
    svc.touch()
    return {"pending": svc.list_pending()}


@router.post("/approvals/{approval_id}")
def approvals_answer(approval_id: str, body: ApprovalAnswer) -> dict[str, Any]:
    from friday.safety.approval import get_approval_service

    if not get_approval_service().resolve(approval_id, body.approved, who="control-center"):
        raise HTTPException(404, "No such pending approval (expired or already answered)")
    return {"ok": True}


@router.get("/audit")
def audit_tail(n: int = 50) -> dict[str, Any]:
    from friday.safety.audit import get_audit_log

    log = get_audit_log()
    ok, msg = log.verify()
    return {"chain_ok": ok, "chain_message": msg, "records": log.tail(max(1, min(n, 500)))}
