"""Calendar iCal parse, agenda helpers, and create URLs (no network)."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "calendar" / "sample.ics"


@pytest.fixture
def sample_ics() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def test_parse_vevent_fields(sample_ics: str):
    from friday.calendar.ical_parse import parse_ics

    events = parse_ics(sample_ics, expand_days=60)
    standup = next(e for e in events if e["uid"] == "standup@friday.test")
    assert standup["summary"] == "Standup"
    assert standup["location"] == "Zoom"
    assert len(standup["attendees"]) == 2
    assert standup["start"].hour == 10
    assert standup["end"].hour == 11


def test_rrule_weekly_expansion(sample_ics: str):
    from friday.calendar.ical_parse import parse_ics

    events = [e for e in parse_ics(sample_ics, expand_days=60) if "Weekly sync" in e["summary"]]
    assert len(events) == 4
    assert all(e["start"].weekday() == 0 for e in events)
    assert events[0]["start"].date() == date(2026, 10, 5)


def test_redact_url():
    from friday.calendar.secrets import redact_url

    url = "https://calendar.google.com/calendar/ical/abc123/private-xyz789/basic.ics"
    red = redact_url(url)
    assert "abc123" not in red
    assert "xyz789" not in red or red.endswith("…c.ics") or "…" in red
    assert red.startswith("https://calendar.google.com")
    assert red.endswith("789") or "…" in red


def test_open_in_chrome_uses_new_tab(monkeypatch):
    from friday.calendar import create as cal_create

    calls = []
    monkeypatch.setattr(cal_create, "_find_chrome", lambda: r"C:\fake\chrome.exe")
    monkeypatch.setattr(
        cal_create.subprocess,
        "Popen",
        lambda args, **_k: calls.append(list(args)) or type("P", (), {})(),
    )
    out = cal_create.open_in_chrome("https://calendar.google.com/")
    assert out["opened"] and out.get("new_tab") is True
    assert calls and calls[0][0].endswith("chrome.exe")
    assert "--new-tab" in calls[0]
    assert calls[0][-1] == "https://calendar.google.com/"


def test_build_template_url_params():
    from friday.calendar.create import build_template_url

    start = datetime(2030, 6, 15, 10, 30)
    end = datetime(2030, 6, 15, 11, 0)
    url = build_template_url(
        "Team sync",
        start,
        end,
        details="Agenda",
        location="Room A",
        guests=["guest@example.com"],
        ctz="America/New_York",
    )
    assert "action=TEMPLATE" in url
    assert "text=Team" in url or "text=Team%20sync" in url
    assert "dates=" in url
    assert "location=Room" in url or "Room%20A" in url
    assert "ctz=America" in url and "New_York" in url
    assert "add=guest" in url


def test_free_slots_from_fixture(sample_ics: str, tmp_path, monkeypatch):
    from friday.calendar import agenda as cal_agenda
    from friday.calendar.secrets import set_ical_url

    db = str(tmp_path / "tasks.sqlite")
    monkeypatch.setattr("friday.config.DATA_DIR", str(tmp_path))
    monkeypatch.setattr("friday.config.TASKS_DB", db)
    monkeypatch.setattr("friday.store.db.TASKS_DB", db)
    monkeypatch.setattr("friday.calendar.secrets.DATA_DIR", str(tmp_path))
    monkeypatch.setattr("friday.calendar.fetch.DATA_DIR", str(tmp_path))
    set_ical_url("https://calendar.example.com/secret/basic.ics")

    def _fake_fetch(*, force: bool = False):
        return sample_ics, False

    monkeypatch.setattr("friday.calendar.fetch.fetch_ical", _fake_fetch)
    monkeypatch.setattr("friday.calendar.agenda.fetch_ical", _fake_fetch)

    day = date(2030, 6, 15)
    slots = cal_agenda.free_slots(day, 30, force_fetch=True)
    assert slots
    assert any("09:00" in s["start"] or "T09:" in s["start"] for s in slots)
    gap = next(s for s in slots if "11:" in s["start"] or "T11:" in s["start"])
    assert "14:" in gap["end"] or "T14:" in gap["end"]
