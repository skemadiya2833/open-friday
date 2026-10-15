"""Diary continuity + blackout privacy mode."""

from __future__ import annotations

from pathlib import Path


def test_diary_record_and_continuity(tmp_path, monkeypatch):
    import friday.config as cfg
    from friday.runtime import diary as D

    monkeypatch.setattr(cfg, "DATA_DIR", Path(tmp_path))
    monkeypatch.delenv("FRIDAY_DIARY_DIR", raising=False)
    path = D.record("Shipped HUD polish", "Reports and Systems cleaned up.", kind="tasks")
    assert Path(path).is_file()
    assert "Shipped HUD polish" in D.read()
    blurb = D.continuity_blurb()
    assert "Today so far" in blurb
    assert "Shipped HUD polish" in blurb
    # Body must not reinject — assistant invents used to poison greetings.
    assert "Reports and Systems" not in blurb


def test_continuity_skips_poisoned_assistant_body(tmp_path, monkeypatch):
    import friday.config as cfg
    from friday.runtime import diary as D

    monkeypatch.setattr(cfg, "DATA_DIR", Path(tmp_path))
    monkeypatch.delenv("FRIDAY_DIARY_DIR", raising=False)
    D.record(
        "I want you to note down my tasks for today",
        'I\'ve noted down your task for today: "Review quarterly financial reports".',
        kind="tasks",
    )
    blurb = D.continuity_blurb()
    assert "quarterly" not in blurb.lower()
    assert "financial reports" not in blurb.lower()
    assert "note down my tasks" not in blurb.lower()


def test_blackout_blocks_research_and_web_tool(monkeypatch):
    from friday.runtime import blackout as B

    monkeypatch.setattr(B, "enabled", lambda: True)
    assert B.blocks_research() is True
    assert B.blocks_tool("web_search") is True
    assert B.blocks_tool("memory_search") is False

    monkeypatch.setattr(B, "enabled", lambda: False)
    assert B.blocks_research() is False
    assert B.blocks_tool("web_search") is False
