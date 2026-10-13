"""AGENT_BACKEND resolution: explicit env vs auto hybrid when Windows-MCP enabled."""

from __future__ import annotations

import friday.agent.backend as be


def test_explicit_legacy(monkeypatch, tmp_path):
    import friday.runtime.prefs as prefs

    monkeypatch.setattr(prefs, "_path", lambda: tmp_path / "runtime_prefs.json")
    prefs.clear_cache()
    be.clear_backend_cache()
    monkeypatch.setenv("AGENT_BACKEND", "legacy")
    monkeypatch.setattr(be, "windows_mcp_enabled", lambda: True)
    assert be.resolve_agent_backend() == "legacy"
    be.clear_backend_cache()


def test_explicit_hybrid(monkeypatch, tmp_path):
    import friday.runtime.prefs as prefs

    monkeypatch.setattr(prefs, "_path", lambda: tmp_path / "runtime_prefs.json")
    prefs.clear_cache()
    be.clear_backend_cache()
    monkeypatch.setenv("AGENT_BACKEND", "hybrid")
    monkeypatch.setattr(be, "windows_mcp_enabled", lambda: False)
    assert be.resolve_agent_backend() == "hybrid"
    be.clear_backend_cache()


def test_auto_hybrid_when_mcp_on(monkeypatch, tmp_path):
    import friday.runtime.prefs as prefs

    monkeypatch.setattr(prefs, "_path", lambda: tmp_path / "runtime_prefs.json")
    prefs.clear_cache()
    be.clear_backend_cache()
    monkeypatch.delenv("AGENT_BACKEND", raising=False)
    monkeypatch.setattr(be, "windows_mcp_enabled", lambda: True)
    assert be.resolve_agent_backend() == "hybrid"
    be.clear_backend_cache()


def test_auto_legacy_when_mcp_off(monkeypatch, tmp_path):
    import friday.runtime.prefs as prefs

    monkeypatch.setattr(prefs, "_path", lambda: tmp_path / "runtime_prefs.json")
    prefs.clear_cache()
    be.clear_backend_cache()
    monkeypatch.delenv("AGENT_BACKEND", raising=False)
    monkeypatch.setattr(be, "windows_mcp_enabled", lambda: False)
    assert be.resolve_agent_backend() == "legacy"
    be.clear_backend_cache()
