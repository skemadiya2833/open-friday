"""Config drift validation (Stage S4)."""

from __future__ import annotations

from friday.diagnostics import config_drift, validate_config


def test_auth_off_warns():
    issues = validate_config({"FRIDAY_AUTH": "off", "FRIDAY_HOST": "127.0.0.1"})
    assert any(i.key == "FRIDAY_AUTH" and i.level == "warn" for i in issues)


def test_lan_host_without_remote_is_error():
    issues = validate_config({"FRIDAY_HOST": "192.168.1.10", "FRIDAY_AUTH": "local"})
    assert any(i.key == "FRIDAY_HOST" and i.level == "error" for i in issues)


def test_shell_tools_warn():
    issues = validate_config({"SHELL_TOOLS_ENABLED": "true", "FRIDAY_HOST": "127.0.0.1"})
    assert any(i.key == "SHELL_TOOLS_ENABLED" and i.level == "warn" for i in issues)


def test_config_drift_detects_shell():
    d = config_drift({"SHELL_TOOLS_ENABLED": "true", "FRIDAY_HOST": "127.0.0.1", "FRIDAY_AUTH": "local"})
    assert d["has_drift"]
    assert "SHELL_TOOLS_ENABLED" in d["drifted"]
