"""Resolve which desktop agent loop to run (legacy vision vs hybrid MCP)."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Literal

BackendName = Literal["legacy", "hybrid"]


def windows_mcp_enabled() -> bool:
    try:
        from friday.mcp_client import get_mcp_manager

        for s in get_mcp_manager().status().get("servers") or []:
            if s.get("name") == "windows" and s.get("enabled"):
                return True
    except Exception:  # noqa: BLE001
        pass
    # Config file even if manager not started yet
    try:
        from friday.config import MCP_CONFIG_PATH
        import yaml

        raw = yaml.safe_load(open(MCP_CONFIG_PATH, encoding="utf-8")) or {}
        win = (raw.get("servers") or {}).get("windows") or {}
        return bool(win.get("enabled"))
    except Exception:  # noqa: BLE001
        return False


@lru_cache(maxsize=1)
def resolve_agent_backend() -> BackendName:
    """Systems UI (legacy|hybrid) → AGENT_BACKEND → auto (hybrid if Windows-MCP on)."""
    # Explicit UI pick (not "auto") wins.
    try:
        from friday.runtime.prefs import load_raw, source_of

        raw = load_raw()
        if "agent_backend" in raw and source_of("agent_backend") == "ui":
            ui = str(raw.get("agent_backend") or "").strip().lower()
            if ui in ("legacy", "hybrid"):
                return ui  # type: ignore[return-value]
    except Exception:  # noqa: BLE001
        pass
    explicit = (os.getenv("AGENT_BACKEND") or "").strip().lower()
    if explicit in ("legacy", "hybrid"):
        return explicit  # type: ignore[return-value]
    if windows_mcp_enabled():
        return "hybrid"
    return "legacy"


def clear_backend_cache() -> None:
    resolve_agent_backend.cache_clear()


def backend_status() -> dict[str, str | bool]:
    choice = "auto"
    src = "auto"
    try:
        from friday.runtime.prefs import load_raw, source_of

        raw = load_raw()
        if "agent_backend" in raw and source_of("agent_backend") == "ui":
            choice = str(raw.get("agent_backend") or "auto").strip().lower() or "auto"
            src = "ui"
        else:
            choice = (os.getenv("AGENT_BACKEND") or "").strip().lower() or "auto"
            src = "env" if choice in ("legacy", "hybrid") else "auto"
    except Exception:  # noqa: BLE001
        choice = (os.getenv("AGENT_BACKEND") or "").strip().lower() or "auto"
        src = "env" if choice in ("legacy", "hybrid") else "auto"
    effective = resolve_agent_backend()
    return {
        "effective": effective,
        "env": choice if choice != "auto" else "(auto)",
        "windows_mcp_enabled": windows_mcp_enabled(),
        "source": src if choice in ("legacy", "hybrid") else "auto",
    }
