"""Model residency — same chat+vision tag must not unload."""

from __future__ import annotations

from friday.models.manager import ModelManager


def test_same_tag_ensure_loaded_does_not_unload(monkeypatch):
    mm = ModelManager()
    unloaded: list[str] = []

    monkeypatch.setattr(mm, "_warmup", lambda model, keep_alive: None)
    monkeypatch.setattr(mm, "_unload", lambda model: unloaded.append(model))
    monkeypatch.setattr("friday.models.manager.resolve_chat_model", lambda: "gemma4:12b")
    monkeypatch.setattr("friday.models.manager.resolve_vision_model", lambda: "gemma4:12b")

    assert mm.ensure_loaded("chat") == "gemma4:12b"
    assert mm.ensure_loaded("vision") == "gemma4:12b"
    assert unloaded == []
    assert mm._loaded == "vision"
    assert mm._loaded_name == "gemma4:12b"


def test_after_vision_keeps_shared_model(monkeypatch):
    mm = ModelManager()
    unloaded: list[str] = []

    monkeypatch.setattr(mm, "_warmup", lambda model, keep_alive: None)
    monkeypatch.setattr(mm, "_unload", lambda model: unloaded.append(model))
    monkeypatch.setattr("friday.models.manager.resolve_chat_model", lambda: "gemma4:12b")
    monkeypatch.setattr("friday.models.manager.resolve_vision_model", lambda: "gemma4:12b")

    mm.ensure_loaded("vision")
    mm.after_vision()
    assert unloaded == []
    assert mm._loaded == "chat"
    assert mm._loaded_name == "gemma4:12b"


def test_after_vision_unloads_when_tags_differ(monkeypatch):
    mm = ModelManager()
    unloaded: list[str] = []
    warmed: list[str] = []

    monkeypatch.setattr(mm, "_warmup", lambda model, keep_alive: warmed.append(model))
    monkeypatch.setattr(mm, "_unload", lambda model: unloaded.append(model))
    monkeypatch.setattr("friday.models.manager.resolve_chat_model", lambda: "qwen3.5:9b")
    monkeypatch.setattr("friday.models.manager.resolve_vision_model", lambda: "qwen3-vl:8b")

    mm.ensure_loaded("vision")
    assert warmed == ["qwen3-vl:8b"]
    mm.after_vision()
    assert unloaded == ["qwen3-vl:8b"]
    assert mm._loaded_name == "qwen3.5:9b"


def test_prefs_change_keeps_shared_resident(monkeypatch):
    mm = ModelManager()
    unloaded: list[str] = []

    monkeypatch.setattr(mm, "_warmup", lambda model, keep_alive: None)
    monkeypatch.setattr(mm, "_unload", lambda model: unloaded.append(model))
    monkeypatch.setattr("friday.models.manager.resolve_chat_model", lambda: "gemma4:12b")
    monkeypatch.setattr("friday.models.manager.resolve_vision_model", lambda: "gemma4:12b")

    mm.ensure_loaded("chat")
    mm.on_prefs_model_change()
    assert unloaded == []
    assert mm._loaded_name == "gemma4:12b"
