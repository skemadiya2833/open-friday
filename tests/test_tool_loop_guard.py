"""Tool-call loop guard (Stage V2) — identical calls, ping-pong, no-change."""

from __future__ import annotations

from friday.agent.tool_loop_guard import LoopGuardConfig, ToolLoopGuard, reset_tool_loop_guard
from friday.tools.registry import ToolRegistry
from friday.tools.types import ToolRisk, ToolResult, ToolSpec


def test_identical_call_blocks_after_warn():
    g = ToolLoopGuard(LoopGuardConfig(max_identical_calls=2, warn_before_block=True))
    assert not g.check_call("type", {"text": "alpha"}).blocked
    assert not g.check_call("type", {"text": "alpha"}).blocked
    # third identical → warn once
    v = g.check_call("type", {"text": "alpha"})
    assert v.warned and not v.blocked
    # fourth → block
    v = g.check_call("type", {"text": "alpha"})
    assert v.blocked and "Identical" in v.reason


def test_ping_pong_ab_pattern():
    g = ToolLoopGuard(LoopGuardConfig(ping_pong_window=6, warn_before_block=False, max_identical_calls=99, poll_tool_budget=99))
    for name in ("click", "type", "click", "type", "click", "type"):
        v = g.check_call(name, {"x": 1})
    assert v.blocked and "ping-pong" in v.reason.lower()


def test_no_change_result():
    g = ToolLoopGuard(LoopGuardConfig(max_no_change=2, warn_before_block=False))
    assert not g.record_result("list_tasks", "same").blocked
    assert not g.record_result("list_tasks", "same").blocked
    v = g.record_result("list_tasks", "same")
    assert v.blocked and "same result" in v.reason


def test_registry_blocks_repeated_bad_tool(monkeypatch):
    reset_tool_loop_guard("run-loop-test")
    reg = ToolRegistry()
    calls = {"n": 0}

    def handler(_args):
        calls["n"] += 1
        return ToolResult.text_result("alpha")

    reg.register(
        ToolSpec(
            name="noop_alpha",
            description="test",
            input_schema={"type": "object", "properties": {}},
            handler=handler,
            risk=ToolRisk.SAFE,
        )
    )
    from friday.safety import policy as P

    class _Allow:
        action = "allow"
        reason = ""

    class _Pol:
        shell = type("S", (), {"is_allowlisted": staticmethod(lambda _c: False)})()

        def decide(self, *a, **k):
            return _Allow()

    monkeypatch.setattr(P, "get_policy", lambda: _Pol())

    results = []
    for _ in range(6):
        results.append(reg.call("noop_alpha", {}, caller="test", run_id="run-loop-test"))
    assert any(r.is_error and "Loop guard" in r.text() for r in results)
    assert calls["n"] < 6


def test_alpha_beta_router_still_ok(tmp_path):
    """Existing notepad alpha/beta direct route must not trip the guard on a single run."""
    from friday.agent import router as RT

    reset_tool_loop_guard()
    r = RT.route(
        f"Open Notepad, type the word alpha, press Enter, type the word beta, "
        f"and save the file as {tmp_path / 'n3.txt'}"
    )
    assert r.handled and r.ok
    assert (tmp_path / "n3.txt").read_bytes() in (b"alpha\nbeta", b"alpha\r\nbeta")
