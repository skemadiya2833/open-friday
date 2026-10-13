"""Week dashboard opens as HTML via tools-first — never vision desktop agent."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from friday.agent.direct_tools import _WEEK_DASHBOARD, try_direct
from friday.assistant import intent as I
from friday.skills.base import SkillContext
from friday.skills.builtin.computer_use.handler import SkillHandler


@pytest.mark.parametrize(
    "text",
    [
        "create a dashboard for all tasks for the week",
        "show me a visual week dashboard",
        "build a weekly task dashboard and display it",
        "week overview dashboard on screen",
    ],
)
def test_week_dashboard_pattern(text):
    assert _WEEK_DASHBOARD.search(text)


def test_intent_routes_dashboard_to_computer_use():
    got = I._deterministic_intent("create a dashboard for all tasks for the week in visual format")
    assert got is not None
    assert got.skill_id == "computer_use"
    assert "dashboard" in (got.reason or "")


def test_try_direct_opens_html(tmp_path, monkeypatch):
    opens: list[str] = []

    monkeypatch.setattr("friday.agent.direct_tools.webbrowser.open", lambda uri: opens.append(uri))
    monkeypatch.setattr("friday.config.DATA_DIR", str(tmp_path))
    monkeypatch.setattr("friday.config.TASKS_DB", str(tmp_path / "t.sqlite"))
    monkeypatch.setattr("friday.store.db.TASKS_DB", str(tmp_path / "t.sqlite"))
    monkeypatch.setattr("friday.tasks.plan.DATA_DIR", str(tmp_path))

    import friday.tasks.plan as plan_mod

    plan_mod._migrated = False
    plan_mod.add_item("Ship release notes")

    with patch("friday.calendar.cache.refresh_from_ical", return_value={"ok": False}):
        out = try_direct("create a dashboard for all tasks for the week")
    assert out.handled and out.ok
    assert out.tool == "week_dashboard"
    assert opens and opens[0].startswith("file:")


def test_computer_use_skill_stays_direct(tmp_path, monkeypatch):
    monkeypatch.setattr("friday.agent.direct_tools.webbrowser.open", lambda *_a, **_k: None)
    monkeypatch.setattr("friday.config.DATA_DIR", str(tmp_path))
    monkeypatch.setattr("friday.config.TASKS_DB", str(tmp_path / "t.sqlite"))
    monkeypatch.setattr("friday.store.db.TASKS_DB", str(tmp_path / "t.sqlite"))
    monkeypatch.setattr("friday.tasks.plan.DATA_DIR", str(tmp_path))
    import friday.tasks.plan as plan_mod

    plan_mod._migrated = False

    events: list[str] = []
    ctx = SkillContext(
        message="create a dashboard for all tasks for the week",
        session_id="t",
        history=[],
        emit=lambda t, *_a, **_k: events.append(t),
    )
    with patch("friday.calendar.cache.refresh_from_ical", return_value={"ok": False}):
        result = SkillHandler().run(ctx)
    assert result.metadata.get("direct") == "week_dashboard"
    assert "computer_use_start" not in events
