"""Unit tests for expanded tools-first direct actions (no live GUI required)."""

from __future__ import annotations

from friday.agent import direct_tools as DT
from friday.agent import router as RT


def test_peripherals_spoken_brief_is_short():
    sample = (
        "Cameras (OpenCV): 3\n"
        "  [MSMF:0] Snap Camera 1280×720\n"
        "  [MSMF:1] SNAP U2 1920×1080\n"
        "Active screens: 2\n"
        "  · \\\\.\\DISPLAY1 1920x1080 (primary)\n"
        "  · \\\\.\\DISPLAY2 1920x1080\n"
        "Audio devices: 4\n"
    )
    brief = DT._peripherals_spoken_brief(sample)
    assert "3 camera" in brief
    assert "2 screen" in brief
    assert "PnP" not in brief
    assert "DISPLAY1" not in brief
    assert len(brief) < 220


def test_open_url_pattern(monkeypatch):
    opened = []
    monkeypatch.setattr(
        "friday.calendar.create.open_in_chrome",
        lambda u: opened.append(u) or {"opened": True, "browser": "chrome", "url": u},
    )
    r = DT.try_direct("open https://example.com")
    assert r.handled and r.tool == "open_url" and r.ok
    assert opened == ["https://example.com"]


def test_open_site_aliases_not_win_search(monkeypatch):
    opened = []
    monkeypatch.setattr(
        "friday.calendar.create.open_in_chrome",
        lambda u: opened.append(u) or {"opened": True, "browser": "chrome", "url": u},
    )
    for msg, expect in (
        ("open youtube", "youtube.com"),
        ("open github.com", "github.com"),
        ("open chrome", "google.com"),
        ("open the browser", "google.com"),
        ("go to reddit", "reddit.com"),
        ("open a site", "google.com"),
    ):
        opened.clear()
        r = DT.try_direct(msg)
        assert r.handled and r.ok and r.tool == "open_url", msg
        assert opened and expect in opened[0], (msg, opened)


def test_open_google_calendar(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "friday.calendar.create.open_in_chrome",
        lambda url: calls.append(url) or {"ok": True, "browser": "chrome", "url": url},
    )
    r = DT.try_direct("open google calendar")
    assert r.handled and r.ok and r.tool == "open_calendar"
    assert "Opened Google Calendar" in r.message
    assert calls and "calendar.google.com" in calls[0]


def test_open_calendar_day_view(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "friday.calendar.create.open_in_chrome",
        lambda url: calls.append(url) or {"ok": True, "browser": "chrome", "url": url},
    )
    r = DT.try_direct("open my calendar day")
    assert r.handled and r.tool == "open_calendar"
    assert "day" in r.message.lower()
    assert calls


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


def test_show_specs_on_screen(monkeypatch, tmp_path):
    opened_urls = []
    pops = []
    monkeypatch.setattr(DT, "_collect_system_specs", lambda: "Friday — System specs\nCPU : test-cpu")
    monkeypatch.setattr(DT.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(DT.webbrowser, "open", lambda u: opened_urls.append(u) or True)
    monkeypatch.setattr(DT.subprocess, "Popen", lambda *a, **k: pops.append(a) or type("P", (), {})())
    r = DT.try_direct("put my system specs on screen")
    assert r.handled and r.ok and r.tool == "show_specs_on_screen"
    assert opened_urls and opened_urls[0].startswith("file:")
    assert list(tmp_path.glob("friday-system-specs-*.html"))
    assert any("powershell" in str(a[0]).lower() for a in pops)


def test_show_system_resources_phrase(monkeypatch, tmp_path):
    """Voice-mangled 'resources on the system … put on screen' must not fall through to vision."""
    monkeypatch.setattr(DT, "_collect_system_specs", lambda: "Friday — System specs\nRAM : 32 GB")
    monkeypatch.setattr(DT.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(DT.webbrowser, "open", lambda u: True)
    monkeypatch.setattr(DT.subprocess, "Popen", lambda *a, **k: type("P", (), {})())
    msg = "Can you bring up my resources that are on the system and put on screen"
    r = DT.try_direct(msg)
    assert r.handled and r.ok and r.tool == "show_specs_on_screen"


def test_list_my_specification_on_screen(monkeypatch, tmp_path):
    """Voice: 'list of my specification … on my screen' must not vision-type into the HUD chat."""
    opened = []
    monkeypatch.setattr(DT, "_collect_system_specs", lambda: "Friday — System specs\nCPU : test")
    monkeypatch.setattr(DT.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(
        "friday.calendar.create.open_in_chrome",
        lambda u: opened.append(u) or {"opened": True, "browser": "chrome", "url": u},
    )
    monkeypatch.setattr(DT.webbrowser, "open", lambda u: opened.append(u) or True)
    monkeypatch.setattr(DT.subprocess, "Popen", lambda *a, **k: type("P", (), {})())
    msg = "Can you list of my specification and put it on my screen"
    r = DT.try_direct(msg)
    assert r.handled and r.ok and r.tool == "show_specs_on_screen"
    assert opened or list(tmp_path.glob("friday-system-specs-*.html"))


def test_router_prefers_direct_before_gui(tmp_path, monkeypatch):
    monkeypatch.setattr(DT.webbrowser, "open", lambda u: True)
    routed = RT.route("open https://example.com", workspace=str(tmp_path))
    assert routed.handled and routed.ok


def test_note_writes_workspace(tmp_path):
    r = DT.try_direct("note that the meeting is at 3", workspace=str(tmp_path))
    assert r.handled and r.ok and "note-" in r.message
