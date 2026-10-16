"""Systems UI runtime prefs: optima defaults, UI override, env fallback."""

from __future__ import annotations

import friday.runtime.prefs as prefs


def test_optima_default_when_unset(tmp_path, monkeypatch):
    monkeypatch.setattr(prefs, "_path", lambda: tmp_path / "runtime_prefs.json")
    prefs.clear_cache()
    monkeypatch.delenv("FRIDAY_HUMOR", raising=False)
    assert prefs.get("humor") == "dry"
    assert prefs.source_of("humor") == "default"


def test_env_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(prefs, "_path", lambda: tmp_path / "runtime_prefs.json")
    prefs.clear_cache()
    monkeypatch.setenv("FRIDAY_HUMOR", "full")
    assert prefs.get("humor") == "full"
    assert prefs.source_of("humor") == "env"


def test_ui_overrides_env(tmp_path, monkeypatch):
    monkeypatch.setattr(prefs, "_path", lambda: tmp_path / "runtime_prefs.json")
    prefs.clear_cache()
    monkeypatch.setenv("FRIDAY_HUMOR", "full")
    prefs.update({"humor": "off"})
    assert prefs.get("humor") == "off"
    assert prefs.source_of("humor") == "ui"


def test_reset_to_optima(tmp_path, monkeypatch):
    monkeypatch.setattr(prefs, "_path", lambda: tmp_path / "runtime_prefs.json")
    prefs.clear_cache()
    prefs.update({"shell_tools": False, "humor": "roast"})
    prefs.reset_to_optima()
    # Optima = SCHEMA defaults (terminal-first → shell_tools on).
    assert prefs.get("shell_tools") is prefs.SCHEMA["shell_tools"]["default"]
    assert prefs.get("shell_tools") is True
    assert prefs.get("humor") == "dry"
    assert prefs.get("tools_first") is True
    assert prefs.get("agent_backend") == "auto"


def test_agent_backend_pref_hybrid(tmp_path, monkeypatch):
    import friday.agent.backend as be

    monkeypatch.setattr(prefs, "_path", lambda: tmp_path / "runtime_prefs.json")
    prefs.clear_cache()
    prefs.update({"agent_backend": "hybrid"})
    be.clear_backend_cache()
    monkeypatch.setattr(be, "windows_mcp_enabled", lambda: False)
    assert be.resolve_agent_backend() == "hybrid"
    be.clear_backend_cache()
