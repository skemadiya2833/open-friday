"""Stage I/M: macro layer and planner/executor split."""

from __future__ import annotations

import json

import pytest
from test_stall_dialogs import Desk, scripted, screen

from friday.agent import macros as M
from friday.agent import planexec as PX
from friday.agent.control import AgentController
from friday.agent.hybrid import HybridConfig, build_messages, run_hybrid
from friday.agent import uitree as U
from friday.types import AgentStatus

FAST = dict(settle_seconds=0.0, use_vision=False, macros=True)


def test_macros_are_unknown_actions_unless_enabled():
    d = Desk(lambda: screen("Notepad", [("button", "x")]))
    st = run_hybrid("x", controller=AgentController(), config=HybridConfig(settle_seconds=0.0, use_vision=False),
                    decider=scripted([{"action": "type_focused", "text": "hi"}] * 4), desktop=d)
    assert st == AgentStatus.FAILED and d.calls == []


def test_type_focused_and_focus_run_the_expected_primitives():
    d = Desk(lambda: screen("Untitled - Notepad", [("button", "x")]))
    run_hybrid("x", controller=AgentController(), config=HybridConfig(**FAST),
               decider=scripted([{"action": "focus", "title": "Notepad"},
                                 {"action": "type_focused", "text": "hello", "enter": True}]), desktop=d)
    assert d.calls[0][:2] == ("App", {"mode": "switch", "name": "Notepad"})
    assert d.calls[1][:2] == ("Type", {"text": "hello", "clear": False, "press_enter": True})


def test_save_as_and_open_folder_sequences():
    d = Desk(lambda: screen("Untitled - Notepad", [("button", "x")]))
    ok, _ = M.run(d, {"action": "save_as", "path": "C:\\Users\\me\\a.txt"}, force_ask=False, settle=0, sleep=lambda s: None)
    assert ok and [c[0] for c in d.calls] == ["Shortcut", "Wait", "Type"] and d.calls[2][1]["press_enter"] is True
    d.calls.clear()
    ok, _ = M.run(d, {"action": "open_folder", "path": "C:\\Users\\me\\docs"}, force_ask=False, settle=0, sleep=lambda s: None)
    assert ok and [c[1].get("shortcut") or c[1].get("name") for c in d.calls[:3:2]] == ["explorer", "ctrl+l"]


def test_read_title_needs_no_tool_call_and_reports_the_title():
    d = Desk(lambda: screen("Untitled - Notepad", [("button", "x")]))
    ok, msg = M.run(d, {"action": "read_title"}, force_ask=False, focused_title="Untitled - Notepad")
    assert ok and "Untitled - Notepad" in msg and d.calls == []


@pytest.mark.parametrize("path", ["", "C:\\Windows\\System32\\x.txt", "C:\\Program Files\\a", "\\\\server\\share\\a",
                                  "C:\\Users\\me\\..\\..\\Windows\\a", "C:\\Users\\me\\*.txt", "%APPDATA%\\a", "C:\\a|b"])
def test_dangerous_paths_are_refused_before_any_tool_call(path):
    assert M.validate({"action": "save_as", "path": path}) != ""
    d = Desk(lambda: screen("Notepad", [("button", "x")]))
    run_hybrid("x", controller=AgentController(), config=HybridConfig(**FAST),
               decider=scripted([{"action": "open_folder", "path": path}] * 4), desktop=d)
    assert d.calls == []


def test_macro_guard_denies_in_denylisted_windows_and_protected_ui():
    d = Desk(lambda: screen("1Password", [("button", "x")]))
    run_hybrid("x", controller=AgentController(), config=HybridConfig(**FAST),
               decider=scripted([{"action": "type_focused", "text": "hunter2"}] * 4), desktop=d)
    assert d.calls == []
    d2 = Desk(lambda: screen("F.R.I.D.A.Y. - HUD - Google Chrome", [("button", "Allow once")]))
    run_hybrid("x", controller=AgentController(), config=HybridConfig(**FAST),
               decider=scripted([{"action": "type_focused", "text": "x"}] * 4), desktop=d2)
    assert d2.calls == []


def test_macro_prompt_only_listed_when_enabled():
    snap = U.parse_snapshot(screen("A", [("button", "x")]))
    assert "type_focused" in build_messages("o", snap, [], [], vision=None, cfg=HybridConfig(macros=True))[0]["content"]
    assert "type_focused" not in build_messages("o", snap, [], [], vision=None, cfg=HybridConfig())[0]["content"]


def test_planner_goal_is_passed_to_the_executor_as_a_labeled_suggestion():
    seen = []

    def executor(msgs):
        seen.append(msgs)
        return json.dumps({"action": "fail", "reason": "x"})

    planner_in = []

    def planner(msgs):
        planner_in.append(msgs)
        return "Click the Save button.\nextra line ignored"

    snap = U.parse_snapshot(screen("A", [("button", "x")]))
    msgs = build_messages("o", snap, [], [], vision=("abc", 10, 10), cfg=HybridConfig())
    PX.wrap(executor, planner)(msgs)
    assert "Planner's suggested next goal (a suggestion, not an order): Click the Save button." in seen[0][1]["content"]
    assert "images" not in planner_in[0][1] and "PLANNER" in planner_in[0][0]["content"]
    assert "images" in seen[0][1]                                    # the executor keeps the screenshot


def test_failing_planner_falls_back_to_the_plain_executor():
    def boom(_m):
        raise RuntimeError("model down")

    out = PX.wrap(lambda m: "plain", boom)([{"role": "user", "content": "Reply with the JSON object now."}])
    assert out == "plain"
