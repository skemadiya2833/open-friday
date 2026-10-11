"""Stage V5: local morning briefing (owner-built-in job)."""

from __future__ import annotations

from friday.briefing.morning import (
    BUILTIN_JOB_ID,
    collect_local_digest,
    compose_spoken_briefing,
    is_enabled,
    set_enabled,
    status,
)


def test_compose_includes_plan_and_persona(tmp_path, monkeypatch):
    monkeypatch.setattr("friday.config.DATA_DIR", str(tmp_path))
    monkeypatch.setattr("friday.tasks.plan.DATA_DIR", str(tmp_path))
    from friday.config import ensure_data_dirs
    from friday.tasks.plan import add_item

    ensure_data_dirs()
    add_item("Ship the briefing")
    digest = {
        "plan": ["Ship the briefing"],
        "reminders": [],
        "weather": "",
        "news": [],
    }
    script = compose_spoken_briefing(digest)
    assert "Ship the briefing" in script
    assert "Good morning" in script


def test_agent_cannot_mark_schedulable():
    st = status()
    assert st["agent_schedulable"] is False
    assert st["job_id"] == BUILTIN_JOB_ID


def test_set_enabled_persists(tmp_path, monkeypatch):
    monkeypatch.delenv("FRIDAY_MORNING_BRIEFING", raising=False)
    monkeypatch.setattr(
        "friday.briefing.morning._settings_path",
        lambda: tmp_path / "briefing_settings.json",
    )

    class _Fake:
        def cancel(self, *_a, **_k):
            return True

        def _conn(self):
            import sqlite3

            c = sqlite3.connect(":memory:")
            c.execute(
                "CREATE TABLE jobs (id TEXT, title TEXT, prompt TEXT, skill_id TEXT, "
                "status TEXT, cron TEXT, run_at REAL, created_at REAL, last_run REAL, meta TEXT)"
            )
            return c

        _lock = __import__("threading").Lock()

        def _arm(self, *_a, **_k):
            return None

    monkeypatch.setattr("friday.tasks.scheduler.get_scheduler", lambda: _Fake())
    assert is_enabled() is False
    out = set_enabled(True, cron="15 7 * * *")
    assert out["enabled"] is True
    assert out["cron"] == "15 7 * * *"


def test_schedule_task_refuses_morning_skill():
    from friday.tools.builtin import _schedule_task

    res = _schedule_task({"prompt": "brief me", "skill_id": "morning_briefing", "title": "x"})
    assert res.is_error
    assert "Refusing" in res.text()
