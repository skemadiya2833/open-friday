"""Compact ops dashboard payload — aggregates existing stores (no new telemetry)."""

from __future__ import annotations

import time
from typing import Any

from friday.config import FRIDAY_AUTH, SERVER_PORT, SERVER_TLS_PORT, resolve_chat_model
from friday.diagnostics.startup import config_drift, validate_config


def ops_summary() -> dict[str, Any]:
    """Side-effect-free summary for /api/ops/summary and Systems UI."""
    t0 = time.perf_counter()
    out: dict[str, Any] = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "auth_mode": FRIDAY_AUTH,
        "ports": {"http": SERVER_PORT, "tls": SERVER_TLS_PORT},
        "models": {},
        "counts": {},
        "health": {"config_errors": 0, "config_warnings": 0, "drift_keys": []},
        "subsystems": {},
    }

    issues = validate_config()
    out["health"]["config_errors"] = sum(1 for i in issues if i.level == "error")
    out["health"]["config_warnings"] = sum(1 for i in issues if i.level == "warn")
    drift = config_drift()
    out["health"]["drift_keys"] = list((drift.get("drifted") or {}).keys())
    out["health"]["has_drift"] = drift.get("has_drift", False)

    try:
        from friday.config import EMBED_MODEL, MODEL_NAME, VISION_MODEL

        out["models"] = {
            "chat": resolve_chat_model(),
            "vision": VISION_MODEL or MODEL_NAME,
            "embed": EMBED_MODEL,
        }
    except Exception as exc:  # noqa: BLE001
        out["models"] = {"error": str(exc)}

    try:
        from friday.assistant.session import SessionStore

        sessions = SessionStore().list_sessions(limit=500)
        out["counts"]["sessions"] = len(sessions)
    except Exception as exc:  # noqa: BLE001
        out["counts"]["sessions"] = None
        out["subsystems"]["sessions"] = str(exc)

    try:
        from friday.agent.runs import get_run_manager

        active = get_run_manager().active()
        out["counts"]["active_runs"] = len(active)
        out["subsystems"]["runs"] = [r.id for r in active[:8]]
    except Exception as exc:  # noqa: BLE001
        out["counts"]["active_runs"] = None

    try:
        from friday.tasks import get_scheduler

        jobs = get_scheduler().list_jobs()
        out["counts"]["scheduled_tasks"] = len(jobs)
        out["counts"]["tasks_enabled"] = sum(1 for j in jobs if j.get("enabled"))
    except Exception as exc:  # noqa: BLE001
        out["counts"]["scheduled_tasks"] = None

    try:
        from friday.memory import get_memory

        st = get_memory().stats()
        out["counts"]["memory_docs"] = sum(st.values()) if isinstance(st, dict) else None
        out["subsystems"]["memory_collections"] = st
    except Exception as exc:  # noqa: BLE001
        out["counts"]["memory_docs"] = None

    try:
        from friday.skills.registry import SkillRegistry

        skills = SkillRegistry().list()
        out["counts"]["skills_total"] = len(skills)
        out["counts"]["skills_enabled"] = sum(1 for s in skills if s.enabled)
    except Exception as exc:  # noqa: BLE001
        out["counts"]["skills_total"] = None

    try:
        from friday.skills.agentskills import get_store

        md = get_store().list_all()
        out["counts"]["skillmd_installed"] = sum(1 for m in md if m.state == "installed")
        out["counts"]["skillmd_quarantine"] = sum(1 for m in md if m.state == "quarantine")
    except Exception as exc:  # noqa: BLE001
        out["counts"]["skillmd_installed"] = None

    try:
        from friday.reports.store import list_reports

        out["counts"]["reports"] = len(list_reports(limit=200))
    except Exception as exc:  # noqa: BLE001
        out["counts"]["reports"] = None

    try:
        from friday.safety.approval import get_approval_service

        pending = get_approval_service().list_pending()
        out["counts"]["approvals_pending"] = len(pending)
    except Exception as exc:  # noqa: BLE001
        out["counts"]["approvals_pending"] = None

    try:
        from friday.mcp_client import get_mcp_manager

        out["subsystems"]["mcp"] = get_mcp_manager().status()
    except Exception as exc:  # noqa: BLE001
        out["subsystems"]["mcp"] = {"error": str(exc)}

    try:
        from friday.diagnostics.startup import ollama_status

        out["subsystems"]["ollama"] = ollama_status(timeout=1.0)
    except Exception as exc:  # noqa: BLE001
        out["subsystems"]["ollama"] = {"error": str(exc)}

    try:
        from friday.experience.store import get_experience

        out["subsystems"]["experience"] = get_experience().stats()
    except Exception as exc:  # noqa: BLE001
        out["subsystems"]["experience"] = {"error": str(exc)}

    out["duration_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return out
