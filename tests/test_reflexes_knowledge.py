"""Fast reflexes + light knowledge graph."""

from __future__ import annotations

from pathlib import Path


def test_reflex_greeting_and_clock(monkeypatch):
    monkeypatch.setenv("FRIDAY_OWNER_NAME", "Sunil")
    monkeypatch.setattr(
        "friday.runtime.prefs.get",
        lambda key, default=None: "Sunil" if key == "owner_name" else default,
    )
    from friday.assistant.reflexes import try_reflex

    g = try_reflex("hello")
    assert g and g.label == "greeting" and "Sunil" in g.reply
    c = try_reflex("what time is it")
    assert c and c.label == "clock"
    assert try_reflex("open notepad and type hello") is None


def test_knowledge_observe(tmp_path, monkeypatch):
    import friday.config as cfg
    from friday.runtime import knowledge as K

    monkeypatch.setattr(cfg, "DATA_DIR", Path(tmp_path))
    touched = K.observe("I've been working on Open Friday HUD polish today")
    assert touched
    block = K.prompt_block()
    assert "Open Friday" in block or "HUD" in block or "project" in block.lower()
