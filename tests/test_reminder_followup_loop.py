"""Reminder follow-up must not loop on mic echo of Friday's own ask."""

from __future__ import annotations

from friday.assistant import intent as I
from friday.skills.builtin.tasks.handler import SkillHandler
from friday.skills.base import SkillContext


def test_echo_of_ask_is_not_reminder_followup():
    hist = [{
        "role": "assistant",
        "content": 'Sure, boss. When should I remind you? Say something like "in 20 minutes".',
    }]
    got = I._deterministic_intent(
        'Sure, boss. When should I remind you? Say something like "in 20 minutes".',
        hist,
    )
    assert got is None or got.skill_id != "tasks" or "follow-up" not in (got.reason or "")


def test_real_time_answer_is_followup():
    hist = [{
        "role": "assistant",
        "content": 'Sure, boss. When should I remind you? Say something like "in 20 minutes".',
    }]
    got = I._deterministic_intent("in 20 minutes", hist)
    assert got and got.skill_id == "tasks" and "follow-up" in got.reason


def test_tasks_skill_breaks_echo_loop():
    skill = SkillHandler()
    ctx = SkillContext(
        message='Sure, boss. When should I remind you? Say something like "in 20 minutes".',
        session_id="t",
        history=[{
            "role": "assistant",
            "content": 'Sure, boss. When should I remind you? Say something like "in 20 minutes".',
        }],
        memory_hits=[],
        skill_override=None,
        voice_mode=True,
        emit=lambda *_: None,
    )
    result = skill.run(ctx)
    assert result.metadata.get("echo_suppressed") or "Still waiting" in (result.reply or "")
    # Must not re-use the ASKED_WHEN phrasing that restarts the loop.
    assert "when should I remind" not in (result.reply or "").lower()
