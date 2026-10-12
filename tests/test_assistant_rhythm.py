"""Stage 2.2 / 2.4 — assistant rhythm, focus, playbooks."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK = ROOT / "skills" / "builtin-playbooks" / "assistant-craft" / "SKILL.md"


def test_inbox_add_and_review(tmp_path, monkeypatch):
    monkeypatch.setattr("friday.config.DATA_DIR", str(tmp_path))
    from friday.assistant.inbox import add, review_summary

    add("Buy milk")
    add("Draft outline")
    summary = review_summary(limit=10)
    assert summary["count"] == 2
    assert len(summary["items"]) == 2


def test_nudge_quiet_hours_blocks(tmp_path, monkeypatch):
    monkeypatch.setattr("friday.config.DATA_DIR", str(tmp_path))
    from friday.assistant import nudges as N

    N.configure(opt_in=True, quiet_start=0, quiet_end=24, daily_cap=5)
    out = N.may_nudge(reason="hydration")
    assert out["allow"] is False
    assert "Quiet hours" in out["why"]


def test_decision_shape():
    from friday.assistant.decision import build_decision

    d = build_decision(
        question="Ship now or polish?",
        option_a="Ship today",
        option_b="Polish two more days",
    )
    assert len(d["options"]) == 2
    assert d["recommendation"]
    assert d["cost_of_delay"]
    assert d["needs_from_owner"]
    assert d["escalation"] is False


def test_focus_parking_lot(tmp_path, monkeypatch):
    monkeypatch.setattr("friday.config.DATA_DIR", str(tmp_path))
    from friday.focus.session import parking_lot_add, parking_lot_list, set_quiet_mode

    set_quiet_mode(True)
    parking_lot_add("Look up tax form")
    items = parking_lot_list()
    assert len(items) == 1
    assert "tax" in items[0]["text"]


def test_playbook_skill_md_parses():
    assert PLAYBOOK.is_file()
    text = PLAYBOOK.read_text(encoding="utf-8")
    from friday.skills.agentskills import split_frontmatter, validate_frontmatter

    fm, body = split_frontmatter(text)
    errs = validate_frontmatter(fm, "assistant-craft")
    assert not errs, errs
    assert "Operating principles" in body


def test_eod_builtin_not_agent_schedulable():
    from friday.briefing.eod import BUILTIN_JOB_ID, status

    st = status()
    assert st["job_id"] == BUILTIN_JOB_ID
    assert st["agent_schedulable"] is False


def test_morning_proposed_top_three_when_plan(tmp_path, monkeypatch):
    monkeypatch.setattr("friday.config.DATA_DIR", str(tmp_path))
    monkeypatch.setattr("friday.tasks.plan.DATA_DIR", str(tmp_path))
    from friday.config import ensure_data_dirs
    from friday.tasks.plan import add_item
    from friday.briefing.morning import collect_local_digest

    def _fake_cal(**_kw):
        return {"available": True, "summary": "Light day.", "events_today": [], "next_events": []}

    monkeypatch.setattr("friday.calendar.load.calendar_load", _fake_cal)
    ensure_data_dirs()
    add_item("One")
    add_item("Two")
    digest = collect_local_digest(fetch_world=False)
    assert len(digest.get("proposed_top_three") or []) >= 2


def test_humor_roast_only_when_explicit(monkeypatch):
    from friday.humor import humor_level, set_humor_override

    set_humor_override(None)
    monkeypatch.delenv("FRIDAY_HUMOR", raising=False)
    assert humor_level() == "dry"
    monkeypatch.setenv("FRIDAY_HUMOR", "roast")
    assert humor_level() == "roast"
    monkeypatch.setenv("FRIDAY_HUMOR", "full")
    assert humor_level() == "full"
