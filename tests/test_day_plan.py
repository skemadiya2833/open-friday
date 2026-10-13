"""Plan-my-day must not store the request as an agenda item."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from friday.skills.base import SkillContext
from friday.skills.builtin.tasks.handler import SkillHandler
from friday.tasks.day_plan import compose_day_plan_reply, is_meta_plan_request, scrub_meta_items
from friday.tasks import plan as plan_mod


@pytest.fixture()
def plan_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("FRIDAY_HUMOR", "off")
    monkeypatch.setattr("friday.config.DATA_DIR", str(tmp_path))
    monkeypatch.setattr("friday.tasks.plan.DATA_DIR", str(tmp_path))
    yield tmp_path


def test_meta_plan_detection():
    assert is_meta_plan_request("plan my day")
    assert is_meta_plan_request("I was thinking maybe you could plan my day")
    assert not is_meta_plan_request("what's the plan")  # list path, not meta-add
    assert not is_meta_plan_request("we'll be doing deep work this afternoon")
    assert not is_meta_plan_request("add ship release notes to my plan")


def test_plan_my_day_does_not_add_utterance(plan_dir, monkeypatch):
    monkeypatch.setenv("FRIDAY_HUMOR", "off")
    with patch("friday.tasks.day_plan._model_outline", return_value=""):
        ctx = SkillContext(message="plan my day", session_id="t", history=[])
        result = SkillHandler().run(ctx)
    assert result.skill_id == "tasks"
    assert "Proposed day" in result.reply or "working plan" in result.reply.lower()
    assert "secret iCal" not in result.reply
    assert "no events loaded" not in result.reply.lower()
    data = plan_mod.get_plan()
    texts = [it.get("text") for it in data.get("items") or []]
    assert "plan my day" not in texts
    assert not any(is_meta_plan_request(t or "") for t in texts)


def test_voice_day_plan_is_short_without_empty_calendar(plan_dir, monkeypatch):
    monkeypatch.setenv("FRIDAY_HUMOR", "off")
    with patch("friday.tasks.day_plan._model_outline", return_value=""):
        built = compose_day_plan_reply(user_text="plan my day", voice_mode=True)
    assert "secret iCal" not in built["reply"]
    assert "no events loaded" not in built["reply"].lower()
    assert "empty — good canvas" not in built["reply"].lower()
    assert "outline" in built["reply"].lower()
    assert len(built["reply"]) < 600


def test_extract_agenda_from_business_dump():
    from friday.tasks.day_plan import extract_agenda_items

    text = (
        "So first thing we will be doing would be to check on everything we have got so far "
        "so we have got a YouTube Uh maybe two we got two YouTube channels and an Instagram page "
        "that I'm planning to grow Along with that I am thinking of a 3D printing business every day at 09:00"
    )
    items = extract_agenda_items(text)
    joined = " ".join(items).lower()
    assert "youtube" in joined
    assert "instagram" in joined
    assert "3d" in joined
    assert "review" in joined or "check" in joined or "everything" in joined


def test_business_dump_is_agenda_not_reminder(plan_dir, monkeypatch):
    monkeypatch.setenv("FRIDAY_HUMOR", "off")
    from friday.tasks import reminders as RM

    text = (
        "So first thing we will be doing would be to check on everything we have got so far "
        "so we have got two YouTube channels and an Instagram page that I'm planning to grow "
        "Along with that I am thinking of a 3D printing business every day at 09:00"
    )
    assert RM.is_agenda_briefing(text)
    assert not RM.is_reminder_request(text)
    assert RM.schedule_from_text(text, use_llm=False) is None

    ctx = SkillContext(message=text, session_id="t", history=[], voice_mode=True)
    result = SkillHandler().run(ctx)
    assert "Locked" in result.reply or "locked" in result.reply.lower()
    assert "YouTube" in result.reply or "youtube" in result.reply.lower()
    # Must not echo the whole monologue as a reminder title
    assert "Uh maybe two" not in result.reply
    data = plan_mod.get_plan()
    texts = " ".join(it.get("text") or "" for it in data.get("items") or []).lower()
    assert "youtube" in texts and "instagram" in texts


def test_thinking_maybe_plan_not_locked_in(plan_dir, monkeypatch):
    monkeypatch.setenv("FRIDAY_HUMOR", "off")
    # Pre-seed the bug the user hit
    plan_mod.add_item("what's the plan")
    plan_mod.add_item("I was thinking maybe you could plan my day")
    with patch("friday.tasks.day_plan._model_outline", return_value=""):
        ctx = SkillContext(
            message="I was thinking maybe you could plan my day",
            session_id="t",
            history=[],
        )
        result = SkillHandler().run(ctx)
    assert "locked in for today" not in result.reply.lower()
    assert "bogus" in result.reply.lower() or "Cleared" in result.reply
    data = plan_mod.get_plan()
    texts = [it.get("text") for it in data.get("items") or []]
    assert not any(is_meta_plan_request(t or "") for t in texts)


def test_scrub_meta_items(plan_dir):
    plan_mod.add_item("real deep work block")
    plan_mod.add_item("plan my day")
    n = scrub_meta_items()
    assert n >= 1
    texts = [it.get("text") for it in plan_mod.get_plan().get("items") or []]
    assert "real deep work block" in texts
    assert "plan my day" not in texts


def test_add_concrete_item_still_works(plan_dir, monkeypatch):
    monkeypatch.setenv("FRIDAY_HUMOR", "off")
    ctx = SkillContext(message="we'll be doing inbox zero this afternoon", session_id="t", history=[])
    result = SkillHandler().run(ctx)
    assert "locked in" in result.reply.lower()
    texts = [it.get("text") for it in plan_mod.get_plan().get("items") or []]
    assert any("inbox" in (t or "").lower() for t in texts)
