"""Run manager (per-run events, cancel) and the global emergency-stop hotkey."""

from __future__ import annotations

import ctypes
import sys
import threading
import time

import pytest
from fastapi.testclient import TestClient

from friday.agent.runs import RunBusyError, RunManager, set_run_manager
from friday.safety.estop import EmergencyStop, emergency_stop, parse_hotkey
from friday.types import AgentStatus
from friday.ui.events import emit, reset_bus


@pytest.fixture()
def mgr(isolated):
    reset_bus()
    m = RunManager()
    set_run_manager(m)
    yield m
    m.cancel_all("teardown")
    for r in m.list():
        r.wait(5)
    set_run_manager(None)


def _spinner(marker: str, n_events: int = 5):
    """Fake agent: emits marker events, then spins until cancelled."""

    def run(objective, ctrl):
        for i in range(n_events):
            emit("tick", marker=marker, i=i)
            time.sleep(0.01)
        while not ctrl.should_stop():
            ctrl.wait_if_paused()
            time.sleep(0.02)
        return AgentStatus.HALTED

    return run


def _finite(marker: str):
    def run(objective, ctrl):
        for i in range(20):
            emit("tick", marker=marker, i=i)
            time.sleep(0.005)
        return AgentStatus.COMPLETED

    return run


def test_start_returns_immediately_and_run_completes(mgr):
    t0 = time.time()
    run = mgr.start("a", _finite("A"), exclusive=False)
    assert time.time() - t0 < 0.5, "start() must not block on the run"
    assert run.wait(10) and run.status == "completed"


def test_concurrent_runs_do_not_leak_events(mgr):
    runs = [mgr.start(f"obj{i}", _finite(f"M{i}"), exclusive=False) for i in range(4)]
    for r in runs:
        assert r.wait(10)
    for i, r in enumerate(runs):
        ticks = [e for e in r.events if e["type"] == "tick"]
        assert len(ticks) == 20
        assert {e["payload"]["marker"] for e in ticks} == {f"M{i}"}, "foreign events leaked into a run"
        assert all(e["run_id"] == r.id for e in r.events)
        types = [e["type"] for e in r.events]
        assert types[0] == "run_start" and types[-1] == "run_end"


def test_events_from_inside_other_threads_of_a_run_are_tagged(mgr):
    """Worker threads started via contextvars.copy_context keep the run tag."""
    import contextvars

    def runner(objective, ctrl):
        ctx = contextvars.copy_context()
        t = threading.Thread(target=lambda: ctx.run(emit, "tick", marker="sub"))
        t.start()
        t.join()
        return AgentStatus.COMPLETED

    r = mgr.start("x", runner, exclusive=False)
    assert r.wait(5)
    assert any(e["type"] == "tick" and e["payload"]["marker"] == "sub" for e in r.events)


def test_exclusive_runs_are_serialized(mgr):
    r1 = mgr.start("one", _spinner("A"))
    with pytest.raises(RunBusyError):
        mgr.start("two", _spinner("B"))
    mgr.cancel(r1.id)
    assert r1.wait(5)
    r3 = mgr.start("three", _finite("C"))      # allowed again
    assert r3.wait(5)


def test_cancel_one_run_leaves_the_other_running(mgr):
    a = mgr.start("a", _spinner("A"), exclusive=False)
    b = mgr.start("b", _spinner("B"), exclusive=False)
    time.sleep(0.2)
    assert mgr.cancel(a.id)
    assert a.wait(5) and a.status == "halted"
    time.sleep(0.2)
    assert not b.done, "cancelling A must not stop B"
    assert all(e["run_id"] == a.id for e in a.events)
    mgr.cancel(b.id)
    assert b.wait(5)


def test_cancel_latency_is_small(mgr):
    r = mgr.start("a", _spinner("A"))
    time.sleep(0.2)
    t0 = time.time()
    mgr.cancel(r.id)
    assert r.wait(5)
    assert time.time() - t0 < 1.0


def test_runner_exception_is_recorded(mgr):
    def boom(objective, ctrl):
        raise RuntimeError("kaput")

    r = mgr.start("a", boom, exclusive=False)
    assert r.wait(5)
    assert r.status == "failed" and "kaput" in r.error


def test_http_cancel_and_single_run_sse(mgr):
    from friday.server.app import app

    r = mgr.start("a", _spinner("A"), exclusive=False)
    other = mgr.start("b", _spinner("B"), exclusive=False)
    time.sleep(0.2)
    with TestClient(app, base_url="http://127.0.0.1:8787") as c:
        assert c.get("/api/runs").status_code == 200
        assert c.post(f"/api/runs/{r.id}/cancel", headers={"Origin": "http://127.0.0.1:8787"}).json()["cancelled"] is True
        assert r.wait(5)
        with c.stream("GET", f"/api/runs/{r.id}/events") as resp:
            body = "".join(resp.iter_text())
        assert '"marker": "A"' in body and '"marker": "B"' not in body
        assert "stream_end" in body
        assert c.get("/api/runs/nope").status_code == 404
        assert not other.done
    mgr.cancel(other.id)


def test_legacy_cancel_endpoint_halts_all(mgr):
    from friday.server.app import app

    a = mgr.start("a", _spinner("A"), exclusive=False)
    b = mgr.start("b", _spinner("B"), exclusive=False)
    time.sleep(0.2)
    with TestClient(app, base_url="http://127.0.0.1:8787") as c:
        assert c.get("/api/agent/status").json()["running"] is True
        assert c.post("/api/agent/cancel").json()["cancelled"] is True
    assert a.wait(5) and b.wait(5)


def test_emergency_stop_function_halts_runs_and_denies_approvals(mgr):
    from friday.safety.approval import get_approval_service

    r = mgr.start("a", _spinner("A"), exclusive=False)
    svc = get_approval_service()
    svc.touch()
    result = {}
    t = threading.Thread(target=lambda: result.setdefault(
        "v", svc.request(tool="write_file", args={}, risk="confirm", caller="t", timeout=30)))
    t.start()
    time.sleep(0.3)
    rep = emergency_stop("test", stop_mcp=False)
    assert r.wait(5) and r.status == "halted"
    t.join(5)
    assert result["v"][0] is False
    assert rep.controllers_cancelled >= 1 and rep.approvals_denied >= 1 and not rep.errors
    from friday.safety.audit import get_audit_log

    assert any(x["tool"] == "emergency_stop" for x in get_audit_log().tail(5))


# ----------------------------------------------------------------------- hotkey
def test_parse_hotkey():
    assert parse_hotkey("ctrl+alt+f12") == (0x2 | 0x1, 0x7B)
    assert parse_hotkey("ctrl+shift+q")[1] == ord("Q")
    for bad in ("f12", "ctrl+", "ctrl+alt+nope", "hyper+f1"):
        with pytest.raises(ValueError):
            parse_hotkey(bad)


def _press(*vks: int) -> None:
    u = ctypes.windll.user32
    for vk in vks:
        u.keybd_event(vk, 0, 0, 0)
        time.sleep(0.03)
    for vk in reversed(vks):
        u.keybd_event(vk, 0, 2, 0)
        time.sleep(0.03)


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 hotkey")
def test_real_hotkey_halts_a_running_agent(mgr):
    """Registers the real global hotkey and injects the key chord; the run must halt."""
    es = EmergencyStop("ctrl+alt+f12", on_trigger=lambda reason: emergency_stop(reason, stop_mcp=False))
    try:
        assert es.start(), es.error
        r = mgr.start("a", _spinner("A"))
        time.sleep(0.3)
        t0 = time.time()
        _press(0x11, 0x12, 0x7B)                    # Ctrl, Alt, F12
        assert r.wait(5), "agent was not halted by the hotkey"
        assert r.status == "halted"
        assert es.trigger_count == 1
        assert time.time() - t0 < 3.0
    finally:
        es.stop()


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 hotkey")
def test_hotkey_conflict_is_reported_not_silent():
    a = EmergencyStop("ctrl+alt+shift+f10")
    b = EmergencyStop("ctrl+alt+shift+f10")
    try:
        assert a.start()
        assert not b.start() and "RegisterHotKey failed" in b.error
    finally:
        a.stop()
        b.stop()
