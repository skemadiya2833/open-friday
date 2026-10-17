"""'What's up for today' must list the plan — never 'couldn't finish cleanly'."""

from __future__ import annotations

from friday.skills.builtin.tasks.handler import SkillHandler, _LIST_TODAY


def test_list_today_matches_natural_asks():
    for msg in (
        "So what's up for today Friday",
        "what's up for today",
        "Tell me the plan for today",
        "what is the plan",
        "agenda for today",
        "show my plan",
    ):
        assert _LIST_TODAY.search(msg), msg


def test_list_today_fast_path_no_hollow(monkeypatch):
    h = SkillHandler()

    class Ctx:
        message = "So what's up for today Friday"
        history = []
        voice_mode = True
        emit = staticmethod(lambda *a, **k: None)

    monkeypatch.setattr(
        "friday.tasks.plan.get_plan",
        lambda: {"date": "2026-10-17", "items": [{"text": "Ship Friday", "done": False}]},
    )
    monkeypatch.setattr("friday.tasks.day_plan.scrub_meta_items", lambda: 0)
    monkeypatch.setattr("friday.humor.maybe_append_quip", lambda reply, **k: reply)

    out = h.run(Ctx())  # type: ignore[arg-type]
    assert out.skill_id == "tasks"
    assert "couldn't finish" not in (out.reply or "").lower()
    assert "try once more" not in (out.reply or "").lower()
    assert "Ship Friday" in (out.reply or "") or "agenda" in (out.reply or "").lower()
