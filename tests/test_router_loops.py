"""Loop breaker (state cycles), composite multi-line typing, tools-first router."""

from __future__ import annotations

from pathlib import Path

from test_stall_dialogs import Desk, scripted, screen

from friday.agent import router as RT
from friday.agent import stall as S
from friday.agent.control import AgentController
from friday.agent.hybrid import HybridConfig, run_hybrid, type_lines
from friday.types import AgentStatus

FAST = dict(settle_seconds=0.0, use_vision=False, tools_first=False)


# ------------------------------------------------------------------ loop breaker
def test_state_cycle_detected_after_returning_twice():
    d = S.StallDetector(max_unchanged=99, max_repeat=99, max_wasted_seconds=999, max_revisits=2)
    seq = ["empty", "alpha", "alpha\n", "alpha\nbeta", "empty", "alpha", "alpha\n", "alpha\nbeta", "empty", "alpha"]
    hit = None
    for i, fp in enumerate(seq):
        hit = d.record(fp, ("a", i))
        if hit:
            break
    assert hit is not None and hit.kind == "state_cycle"


def test_progress_without_revisits_is_not_a_cycle():
    d = S.StallDetector(max_unchanged=99, max_repeat=99, max_wasted_seconds=999)
    assert all(d.record(f"s{i}", ("a", i)) is None for i in range(30))


def test_recovery_skips_to_alternative_for_cycles():
    r = S.Recovery()
    assert r.next(at_least="alternative") == "alternative"


def test_cycling_agent_is_stopped_and_told_why():
    state = {"n": 0}
    titles = ["A", "B"]

    d = Desk(lambda: screen(titles[state["n"] % 2], [("button", f"b{state['n'] % 2}")]),
             on_call=lambda t, a: state.__setitem__("n", state["n"] + 1))
    plans = [{"action": "click", "id": 0, "text": str(i)} for i in range(40)]
    st = run_hybrid("x", controller=AgentController(), config=HybridConfig(max_steps=40, **FAST), decider=scripted(plans), desktop=d)
    assert st == AgentStatus.FAILED
    assert len(d.calls) < 20


# ------------------------------------------------------------------ composite typing
def test_type_lines_clicks_once_and_uses_enter_between_lines():
    d = Desk(lambda: screen("Notepad", [("button", "x")]))
    res = type_lines(d, "alpha\nbeta\ngamma", {"text": "", "clear": True, "press_enter": False, "loc": [5, 5]}, force_ask=False)
    assert not res.is_error
    types = [c for c in d.calls if c[0] == "Type"]
    assert [t[1]["text"] for t in types] == ["alpha", "beta", "gamma"]
    assert types[0][1]["loc"] == [5, 5] and types[0][1]["clear"] is True
    assert all("loc" not in t[1] and t[1]["clear"] is False for t in types[1:])
    assert [c[1]["shortcut"] for c in d.calls if c[0] == "Shortcut"] == ["enter", "enter"]


def test_type_lines_keeps_blank_lines():
    d = Desk(lambda: screen("Notepad", [("button", "x")]))
    type_lines(d, "a\n\nb", {"clear": False, "press_enter": True}, force_ask=False)
    assert [c[0] for c in d.calls] == ["Type", "Shortcut", "Shortcut", "Type"]
    assert d.calls[-1][1]["press_enter"] is True


# ------------------------------------------------------------------ router
def P(tmp: Path, name: str) -> str:
    return str(tmp / name)


def test_parse_simple_and_two_lines_and_edit(tmp_path):
    assert RT.parse_text_objective(f"Open Notepad, type exactly: hello friday  then save the file as {P(tmp_path, 'a.txt')}") == (P(tmp_path, "a.txt"), "hello friday")
    assert RT.parse_text_objective(
        f"Open Notepad, type the word alpha, press Enter, type the word beta, and save the file as {P(tmp_path, 'b.txt')}") == (P(tmp_path, "b.txt"), "alpha\nbeta")
    assert RT.parse_text_objective(
        f"Open Notepad, type: temp  then select all and delete it, type: final  and save as {P(tmp_path, 'c.txt')}") == (P(tmp_path, "c.txt"), "final")
    assert RT.parse_text_objective(f"Open Notepad, type: nested ok  and save it as {P(tmp_path, 'sub')}\\n5.txt (the folder already exists).")[1] == "nested ok"


def test_parse_declines_what_it_does_not_understand(tmp_path):
    assert RT.parse_text_objective(f"Open Notepad, type hi and then close Notepad, save as {P(tmp_path, 'a.txt')}") is None
    assert RT.parse_text_objective("Open Notepad and write a poem") is None
    assert RT.parse_text_objective(f"type hi, make it bold, save as {P(tmp_path, 'a.txt')}") is None


def test_route_writes_new_file_in_temp(tmp_path):
    r = RT.route(f"Open Notepad, type the word alpha, press Enter, type the word beta, and save the file as {P(tmp_path, 'n3.txt')}")
    assert r.handled and r.ok
    assert (tmp_path / "n3.txt").read_bytes() == b"alpha\nbeta"


def test_route_refuses_overwrite_unsafe_extensions_and_system_paths(tmp_path):
    (tmp_path / "x.txt").write_text("keep", encoding="utf-8")
    assert not RT.route(f"type hi and save it as {P(tmp_path, 'x.txt')}").handled
    assert (tmp_path / "x.txt").read_text(encoding="utf-8") == "keep"
    assert not RT.route(f"type calc and save it as {P(tmp_path, 'run.bat')}").handled
    assert not RT.route("type hi and save it as C:\\Windows\\System32\\a.txt").handled
    assert not RT.route(f"type hi and save it as {P(tmp_path, 'missing')}\\a.txt").handled


def test_route_needs_approval_outside_scratch(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(RT.Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(RT.tempfile, "gettempdir", lambda: str(tmp_path / "tmp"))
    obj = f"type hello and save it as {home / 'n.txt'}"
    assert not RT.route(obj).handled                       # no approver -> falls back to the GUI
    assert not RT.route(obj, approve=lambda p, w: False).handled
    assert RT.route(obj, approve=lambda p, w: True).handled
    assert (home / "n.txt").read_text(encoding="utf-8") == "hello"


def test_run_hybrid_uses_router_before_any_desktop_or_grant(tmp_path):
    out = tmp_path / "n.txt"
    st = run_hybrid(f"Open Notepad, type: hello friday  then save the file as {out}", controller=AgentController(),
                    config=HybridConfig(tools_first=True, grant_issuer="test"), decider=scripted([]))
    assert st == AgentStatus.COMPLETED and out.read_text(encoding="utf-8") == "hello friday"
