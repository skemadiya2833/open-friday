"""Artemis MCP wiring — pref + launcher + mcp config (no network clone in CI)."""

from __future__ import annotations

from pathlib import Path

from friday.mcp_client.config import load_config
from friday.runtime import bootstrap_integrations as boot
from friday.runtime import prefs


def test_artemis_pref_exists():
    assert "artemis_enabled" in prefs.SCHEMA
    assert prefs.SCHEMA["artemis_enabled"]["default"] is False


def test_artemis_mcp_server_in_config():
    cfg = load_config()
    assert "artemis" in cfg.servers
    s = cfg.servers["artemis"]
    assert s.enabled is False
    assert any("artemis_mcp.py" in a for a in s.args)
    assert "mobile_run_task" in s.risk_confirm


def test_artemis_launcher_script_exists():
    root = Path(__file__).resolve().parents[1]
    assert (root / "scripts" / "artemis_mcp.py").is_file()


def test_artemis_dir_defaults_under_data(tmp_path, monkeypatch):
    monkeypatch.delenv("FRIDAY_ARTEMIS_DIR", raising=False)
    monkeypatch.setattr("friday.config.DATA_DIR", str(tmp_path))
    assert boot.artemis_dir() == tmp_path / "vendor" / "artemis"
    assert boot.artemis_ready() is False
