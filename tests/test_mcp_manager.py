"""MCP client manager against a real stdio server (tests/fixtures/echo_mcp_server.py)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from friday.mcp_client.config import McpConfigError, parse_config
from friday.mcp_client.manager import McpManager
from friday.safety.policy import Policy, set_policy
from friday.tools.registry import ToolRegistry
from friday.tools.types import ToolRisk

FIXTURE = str(Path(__file__).parent / "fixtures" / "echo_mcp_server.py")


def _cfg(**server_over):
    server = {
        "command": sys.executable,
        "args": [FIXTURE],
        "enabled": True,
        "startup_timeout_seconds": 60,
        "call_timeout_seconds": 20,
        "env": {"ANONYMIZED_TELEMETRY": "false"},
        "risk": {"default": "confirm", "safe": ["echo", "add"], "dangerous": ["dangerous_thing"]},
    }
    server.update(server_over)
    return parse_config({"version": 1, "servers": {"t": server}})


@pytest.fixture()
def mgr(isolated, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "super-secret-should-not-leak")
    reg = ToolRegistry()
    m = McpManager(_cfg(), registry=reg)
    m.load()
    yield m
    m.shutdown()


def test_discovery_registers_namespaced_tools_with_tiers(mgr):
    mgr.start("t")
    assert mgr.wait_ready("t", 60), mgr.status()
    reg = mgr.registry
    names = {t.name: t for t in reg.list()}
    assert set(names) == {"t__echo", "t__add", "t__dangerous_thing", "t__fail", "t__env_flag"}
    assert names["t__echo"].risk is ToolRisk.SAFE
    assert names["t__dangerous_thing"].risk is ToolRisk.DANGEROUS
    assert names["t__fail"].risk is ToolRisk.CONFIRM       # unlisted -> default
    assert names["t__add"].input_schema["properties"]["a"]["type"] == "integer"  # real schema from server
    assert all(t.source == "mcp:t" for t in names.values())


def test_call_goes_through_policy_and_returns_structured(mgr, isolated):
    mgr.start("t")
    assert mgr.wait_ready("t", 60)
    res = mgr.registry.call("t__add", {"a": 2, "b": 5})
    assert res.text() == "7" and res.structured == {"result": 7}
    assert res.metadata["untrusted"] is True
    assert isolated.audit.tail(1)[0]["tool"] == "t__add"
    # invalid args are rejected client-side by the discovered schema
    assert mgr.registry.call("t__add", {"a": "x", "b": 1}).is_error
    # dangerous tier is denied by policy, server never reached
    assert mgr.registry.call("t__dangerous_thing", {"path": "C:/x"}).metadata.get("denied")
    # confirm tier without a responder fails closed
    assert mgr.registry.call("t__fail", {}).metadata.get("denied")


def test_server_errors_become_error_results(mgr):
    set_policy(Policy.from_dict({"tools": {"t__fail": "allow"}}))
    mgr.start("t")
    assert mgr.wait_ready("t", 60)
    res = mgr.registry.call("t__fail", {})
    assert res.is_error


def test_env_is_scrubbed_and_telemetry_forced_off(mgr):
    set_policy(Policy.from_dict({"tools": {"t__env_flag": "allow"}}))
    mgr.start("t")
    assert mgr.wait_ready("t", 60)
    out = mgr.registry.call("t__env_flag", {}).text()
    assert out == "false|<no-secret>"


def test_stop_and_kill_switch_remove_tools(mgr):
    mgr.start("t")
    assert mgr.wait_ready("t", 60)
    assert mgr.registry.list()
    assert mgr.kill_all() == 1
    assert mgr.registry.list() == []
    assert mgr.status()[0]["status"] == "stopped"
    # can be started again after the kill switch
    mgr.start("t")
    assert mgr.wait_ready("t", 60)
    assert mgr.registry.get("t__echo") is not None


def test_exclude_tools_dropped_client_side(isolated):
    m = McpManager(_cfg(exclude_tools=["fail", "env_flag"]), registry=ToolRegistry())
    m.load()
    try:
        m.start("t")
        assert m.wait_ready("t", 60)
        assert {t.name for t in m.registry.list()} == {"t__echo", "t__add", "t__dangerous_thing"}
    finally:
        m.shutdown()


def test_bad_command_reports_error_not_crash(isolated):
    m = McpManager(_cfg(command="definitely-not-a-real-binary-xyz"), registry=ToolRegistry())
    m.load()
    try:
        m.start("t")
        assert not m.wait_ready("t", 20)
        st = m.status()[0]
        assert st["status"] == "error" and "not found" in st["error"]
    finally:
        m.shutdown()


def test_annotations_ignored_unless_trusted():
    cfg = parse_config({"servers": {"s": {"command": "x", "risk": {"default": "confirm"}}}}).servers["s"]
    assert cfg.risk_for("T", {"read_only_hint": True}) is ToolRisk.CONFIRM
    cfg.trust_annotations = True
    assert cfg.risk_for("T", {"read_only_hint": True}) is ToolRisk.SAFE


def test_config_validation():
    with pytest.raises(McpConfigError):
        parse_config({"servers": {"bad name!": {"command": "x"}}})
    with pytest.raises(McpConfigError):
        parse_config({"servers": {"s": {}}})
    with pytest.raises(McpConfigError):
        parse_config({"servers": {"s": {"command": "x", "risk": {"safe": ["a"], "dangerous": ["a"]}}}})
    with pytest.raises(McpConfigError):
        parse_config({"servers": {"s": {"command": "x", "risk": {"default": "yolo"}}}})


def test_shipped_config_is_valid_and_safe_by_default():
    from friday.mcp_client.config import load_config

    cfg = load_config()
    w = cfg.servers["windows"]
    assert w.enabled is False                         # desktop control is opt-in
    assert "--exclude-tools" in w.args and "PowerShell,Registry" in w.args
    assert w.env["ANONYMIZED_TELEMETRY"] == "false"
    assert any(a.startswith("windows-mcp==") for a in w.args)   # pinned
    assert "PowerShell" in w.exclude_tools and "Registry" in w.exclude_tools
