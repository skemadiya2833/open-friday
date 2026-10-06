"""Shared test fixtures: isolate data dir, audit log, policy and approvals per test."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture()
def isolated(tmp_path, monkeypatch):
    """Fresh workspace, audit log, default policy and approval service."""
    import friday.tools.registry as reg
    from friday.safety.approval import ApprovalService, set_approval_service
    from friday.safety.audit import AuditLog, set_audit_log
    from friday.safety.policy import Policy, set_policy

    ws = tmp_path / "workspace"
    ws.mkdir()
    monkeypatch.setattr(reg, "WORKSPACE_DIR", str(ws))
    audit = AuditLog(tmp_path / "audit" / "calls.jsonl")
    set_audit_log(audit)
    set_policy(Policy())
    svc = ApprovalService(default_timeout=5)
    set_approval_service(svc)
    reg.reset_registry()
    yield type("Env", (), {"workspace": ws, "audit": audit, "approvals": svc, "tmp": tmp_path})()
    set_audit_log(None)
    set_policy(None)
    set_approval_service(None)
    reg.reset_registry()
