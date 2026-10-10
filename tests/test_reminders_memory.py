"""Agentic reminders, notifications, automatic memory, plain-chat fast path."""

from __future__ import annotations

from datetime import datetime

import pytest

from friday.assistant import automemory as AM
from friday.assistant import intent as I
from friday.tasks import reminders as RM

NOW = datetime(2026, 10, 7, 10, 0)


@pytest.mark.parametrize("text,title,kind", [
    ("schedule a task tomorrow at 9am to submit the report", "Submit the report", "run"),
    ("Remind me to call mum in 20 minutes", "Call mum", "run"),
    ("remind me to drink water every 2 hours", "Drink water", "cron"),
    ("Friday, remind me tomorrow at 9am to send the invoice", "Send the invoice", "run"),
    ("remind me at 8:30 pm to take medicine", "Take medicine", "run"),
    ("every weekday at 9 remind me to check mail", "Check mail", "cron"),
    ("remind me on monday at 10 to submit report", "Submit report", "run"),
])
def test_parse_when_and_title(text, title, kind):
    w = RM.parse_when(text, NOW)
    assert w is not None and RM.make_title(text, w) == title
    assert (w.cron is not None) == (kind == "cron")
    if w.run_at:
        assert w.run_at > NOW.timestamp()


def test_bare_clock_means_next_occurrence():
    assert datetime.fromtimestamp(RM.parse_when("remind me at 5 to stretch", NOW).run_at).hour == 17
    assert datetime.fromtimestamp(RM.parse_when("remind me at 9 to call", NOW).run_at).hour == 21   # 09:00 already passed
    late = datetime(2026, 10, 7, 22, 0)
    w = datetime.fromtimestamp(RM.parse_when("remind me at 9 to call", late).run_at)
    assert (w.day, w.hour) == (8, 9)


def test_no_time_means_no_schedule():
    assert RM.parse_when("remind me to buy milk", NOW) is None
    assert RM.schedule_from_text("remind me to buy milk", use_llm=False) is None


def test_schedule_creates_job_and_fires_notification(tmp_path, monkeypatch):
    import friday.tasks.reminders as rm
    import friday.tasks.scheduler as sch

    db = str(tmp_path / "t.sqlite")
    monkeypatch.setattr(rm, "TASKS_DB", db)
    monkeypatch.setattr(sch, "TASKS_DB", db)
    monkeypatch.setattr(sch, "_sched", None)
    monkeypatch.setenv("FRIDAY_TOASTS", "off")
    made = rm.schedule_from_text("remind me to stretch in 2 hours", use_llm=False)
    assert made and made["job"]["skill_id"] == "reminder" and "Stretch" in made["reply"]
    sch.get_scheduler()._execute(made["job"]["id"])
    n = rm.list_notifications(unseen_only=True)
    assert len(n) == 1 and n[0]["title"] == "Stretch"
    assert rm.mark_seen(n[0]["id"]) == 1 and rm.list_notifications(unseen_only=True) == []
    sch._sched = None


def test_missed_reminder_is_delivered_after_restart(tmp_path, monkeypatch):
    import time as _t

    import friday.tasks.reminders as rm
    import friday.tasks.scheduler as sch

    db = str(tmp_path / "t.sqlite")
    monkeypatch.setattr(rm, "TASKS_DB", db)
    monkeypatch.setattr(sch, "TASKS_DB", db)
    monkeypatch.setattr(sch, "_sched", None)
    monkeypatch.setenv("FRIDAY_TOASTS", "off")
    s = sch.get_scheduler()
    job = s.add_job(prompt="Pay rent", skill_id="reminder", delay_seconds=3600, title="Pay rent")
    import sqlite3
    with sqlite3.connect(db) as c:
        c.execute("UPDATE jobs SET run_at=? WHERE id=?", (_t.time() - 600, job["id"]))
    monkeypatch.setattr(sch, "_sched", None)
    sch.get_scheduler()
    for _ in range(80):
        if rm.list_notifications():
            break
        _t.sleep(0.1)
    got = rm.list_notifications()
    assert got and got[0]["title"] == "Pay rent" and "missed" in got[0]["body"]
    sch._sched = None


# ------------------------------------------------------------------ memory
@pytest.mark.parametrize("msg,fact", [
    ("my name is Stark", "The owner's name is Stark"),
    ("I live in New York", "The owner lives in New York"),
    ("I love strong black coffee", "The owner loves strong black coffee"),
    ("my favorite editor is Cursor", "The owner's favorite editor is Cursor"),
    ("remember that the wifi router is in the hall", "the wifi router is in the hall"),
])
def test_extracts_facts(msg, fact):
    assert AM.extract(msg) == [fact]


def test_does_not_store_secrets_or_questions():
    assert AM.extract("remember that my password is hunter2") == []
    assert AM.extract("my card number is 4111111111111111") == []
    assert AM.extract("do you remember that I like tea?") == []
    assert AM.extract("what is the weather") == []


# ------------------------------------------------------------------ routing
def test_reminders_route_to_tasks_without_the_classifier():
    got = I._deterministic_intent("remind me to call mum in 20 minutes")
    assert got and got.skill_id == "tasks"
    assert I._deterministic_intent("schedule a task tomorrow at 9 to submit the report").skill_id == "tasks"


def test_reminder_followup_stays_on_tasks():
    hist = [{"role": "assistant", "content": "Sure, boss. When should I remind you? Say something like \"in 20 minutes\"."}]
    got = I._deterministic_intent("tomorrow at 9 send the invoice", hist)
    assert got and got.skill_id == "tasks"


def test_plain_conversation_skips_the_classifier_but_tools_do_not():
    assert I._deterministic_intent("tell me a joke about cats").skill_id == "chat"
    assert I._deterministic_intent("remember that I like tea").skill_id == "chat"
    assert I._deterministic_intent("what's the capital of France") .skill_id == "chat"
    # Explicit web lookup routes deterministically to research (no LLM classifier).
    assert I._deterministic_intent("search the web for rust tutorials").skill_id == "research"
    assert I._deterministic_intent("open notepad and type hello").skill_id == "computer_use"
