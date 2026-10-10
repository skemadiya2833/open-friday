"""Unit tests for expanded tools-first direct actions (no live GUI required)."""

from __future__ import annotations

from friday.agent import direct_tools as DT
from friday.agent import router as RT


def test_open_url_pattern(monkeypatch):
    opened = []
    monkeypatch.setattr(DT.webbrowser, "open", lambda u: opened.append(u) or True)
    r = DT.try_direct("open https://example.com")
    assert r.handled and r.tool == "open_url" and r.ok
    assert opened == ["https://example.com"]


def test_open_app_notepad_only(monkeypatch):
    calls = []
    monkeypatch.setattr(DT.subprocess, "Popen", lambda *a, **k: calls.append(a) or type("P", (), {})())
    r = DT.try_direct("open notepad")
    assert r.handled and r.tool == "open_app"
    assert calls


def test_open_app_with_type_falls_through():
    r = DT.try_direct("open notepad and type hello")
    assert not r.handled


def test_clipboard_roundtrip():
    set_r = DT.try_direct("copy to clipboard: friday-direct-test-xyz")
    assert set_r.handled and set_r.ok
    get_r = DT.try_direct("what is on the clipboard?")
    assert get_r.handled and "friday-direct-test-xyz" in get_r.message


def test_status_pattern():
    r = DT.try_direct("system status")
    assert r.handled and r.tool == "system_status"


def test_router_prefers_direct_before_gui(tmp_path, monkeypatch):
    monkeypatch.setattr(DT.webbrowser, "open", lambda u: True)
    routed = RT.route("open https://example.com", workspace=str(tmp_path))
    assert routed.handled and routed.ok


def test_note_writes_workspace(tmp_path):
    r = DT.try_direct("note that the meeting is at 3", workspace=str(tmp_path))
    assert r.handled and r.ok and "note-" in r.message
