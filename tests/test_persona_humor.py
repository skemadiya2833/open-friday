"""Persona + humor policy unit tests (no model required)."""

from __future__ import annotations



from friday.agent.behavior import (
    deep_mode_enabled,
    looks_multi_step,
    plan_preamble,
    with_plan_if_needed,
)
from friday.humor import (
    humor_level,
    maybe_append_quip,
    pick_fallback_quip,
    should_quip,
)
from friday.persona import format_persona, owner_name, system_prompt


def test_persona_formats_owner(monkeypatch):
    monkeypatch.setenv("FRIDAY_OWNER_NAME", "chief")

    def _pref(key, default=None):
        return "chief" if key == "owner_name" else default

    monkeypatch.setattr("friday.runtime.prefs.get", _pref)
    assert owner_name() == "chief"
    text = system_prompt("chat")
    assert "chief" in text
    assert "Tony Stark" not in text
    assert "MCU" not in text
    assert "film character" in text.lower() or "run the house" in text.lower() or "f.r.i.d.a.y" in text.lower()


def test_humor_off(monkeypatch):
    monkeypatch.setenv("FRIDAY_HUMOR", "off")

    def _pref(key, default=None):
        return "off" if key == "humor" else default

    monkeypatch.setattr("friday.runtime.prefs.get", _pref)
    assert humor_level() == "off"
    assert should_quip(user_text="hello", reply="Hi there.") is False
    assert maybe_append_quip("All done.", user_text="hello") == "All done."


def test_humor_skips_stress_and_errors(monkeypatch):
    monkeypatch.setenv("FRIDAY_HUMOR", "dry")
    assert should_quip(user_text="This is urgent emergency", reply="Ok.") is False
    assert should_quip(user_text="hi", reply="Error: failed", is_error=False) is False
    assert should_quip(user_text="hi", reply="Ok.", is_security=True) is False


def test_no_stock_fallback_quip(monkeypatch):
    monkeypatch.setenv("FRIDAY_HUMOR", "dry")
    assert pick_fallback_quip() is None
    assert maybe_append_quip("All done.", user_text="hello") == "All done."


def test_deep_and_plan_helpers():
    assert deep_mode_enabled("please think carefully about this")
    assert looks_multi_step("Open Notepad then type hello and finally save")
    plan = plan_preamble("do the thing")
    assert "Execute for real" in plan
    assert "verify" in plan.lower()
    assert "Objective: do the thing" in plan
    combined = with_plan_if_needed(
        "SYS", "first open chrome then search the news and finally save a note"
    )
    assert "Execute for real" in combined
    assert "Objective:" in combined


def test_format_persona_placeholder():
    out = format_persona("Hello {owner}")
    assert "{owner}" not in out
