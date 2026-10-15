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
    db = str(tmp_path / "tasks.sqlite")
    monkeypatch.setattr("friday.config.DATA_DIR", str(tmp_path))
    monkeypatch.setattr("friday.config.TASKS_DB", db)
    monkeypatch.setattr("friday.store.db.TASKS_DB", db)
    monkeypatch.setattr("friday.tasks.plan.DATA_DIR", str(tmp_path))
    # Force schema re-init against the temp DB.
    import friday.store.db as store_db

    monkeypatch.setattr(store_db, "_schema_ready", False)
    yield tmp_path


def test_meta_plan_detection():
    assert is_meta_plan_request("plan my day")
    assert is_meta_plan_request("I was thinking maybe you could plan my day")
    assert not is_meta_plan_request("what's the plan")  # list path, not meta-add
    assert not is_meta_plan_request("we'll be doing deep work this afternoon")
    assert not is_meta_plan_request("add ship release notes to my plan")


def test_empty_task_capture_asks_not_invents(plan_dir, monkeypatch):
    from friday.tasks.day_plan import is_empty_task_capture

    monkeypatch.setenv("FRIDAY_HUMOR", "off")
    assert is_empty_task_capture("note down my tasks for today")
    assert is_empty_task_capture("write down my todos")
    assert is_empty_task_capture("I want you to note down my tasks for today")
    assert is_empty_task_capture("can you jot down my todos please")
    assert not is_empty_task_capture("what's on my tasks for today")
    assert not is_empty_task_capture("note down buy milk and call mom")

    # No senses → ask, do not invent quarterly chores.
    with patch("friday.tasks.day_plan._model_task_proposals", return_value=[]):
        with patch("friday.tasks.day_plan.gather_day_context", return_value={
            "plan": plan_mod.get_plan(),
            "open_items": [],
            "calendar": [],
            "diary": [],
            "profile": "",
            "knowledge": [],
            "has_signal": False,
        }):
            ctx = SkillContext(
                message="note down my tasks for today", session_id="t", history=[], voice_mode=True
            )
            result = SkillHandler().run(ctx)
    assert "hit me with the tasks" in result.reply.lower() or "don't have" in result.reply.lower()
    assert "quarterly" not in result.reply.lower()
    assert result.metadata.get("awaiting_tasks") is True
    assert not (plan_mod.get_plan().get("items") or [])

    follow = SkillContext(
        message="inbox zero, ship the Friday HUD, and gym at 6",
        session_id="t",
        history=[
            {"role": "user", "content": "note down my tasks for today"},
            {"role": "assistant", "content": result.reply},
        ],
        voice_mode=True,
    )
    locked = SkillHandler().run(follow)
    assert "locked in" in locked.reply.lower()
    texts = " ".join(it.get("text") or "" for it in plan_mod.get_plan().get("items") or []).lower()
    assert "inbox" in texts and "friday" in texts


def test_task_capture_proposes_from_senses(plan_dir, monkeypatch):
    monkeypatch.setenv("FRIDAY_HUMOR", "off")
    with patch(
        "friday.tasks.day_plan._model_task_proposals",
        return_value=["Standup with design", "Ship Friday HUD polish"],
    ):
        with patch(
            "friday.tasks.day_plan.gather_day_context",
            return_value={
                "plan": plan_mod.get_plan(),
                "open_items": [],
                "calendar": ["10:00 Standup with design"],
                "diary": ["HUD polish yesterday"],
                "profile": "",
                "knowledge": [],
                "has_signal": True,
            },
        ):
            ctx = SkillContext(
                message="note down my tasks for today", session_id="t", history=[], voice_mode=True
            )
            result = SkillHandler().run(ctx)
    assert "from what i can see" in result.reply.lower() or "i'd put" in result.reply.lower()
    assert "standup" in result.reply.lower()
    assert "quarterly" not in result.reply.lower()
    assert result.metadata.get("proposed")

    locked = SkillHandler().run(
        SkillContext(
            message="lock these in",
            session_id="t",
            history=[
                {"role": "user", "content": "note down my tasks for today"},
                {"role": "assistant", "content": result.reply},
            ],
            voice_mode=True,
        )
    )
    assert "locked in" in locked.reply.lower()
    texts = " ".join(it.get("text") or "" for it in plan_mod.get_plan().get("items") or []).lower()
    assert "standup" in texts or "hud" in texts


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
