"""Vision must not send screenshots to a text-only GGUF."""

from __future__ import annotations

from friday import config as C


def test_text_gguf_detected():
    assert C._name_looks_text_only("qwen3.8-27b-iq3s")
    assert not C._name_looks_vision("qwen3.8-27b-iq3s")


def test_vl_tag_detected():
    assert C._name_looks_vision("qwen3-vl:8b-instruct")
    assert not C._name_looks_text_only("qwen3-vl:8b-instruct")
    assert C._name_looks_vision("gemma4:12b")
    assert not C._name_looks_text_only("gemma4:12b")


def test_resolve_vision_falls_back_from_iq3(tmp_path, monkeypatch):
    import friday.runtime.prefs as prefs

    monkeypatch.setattr(prefs, "_path", lambda: tmp_path / "runtime_prefs.json")
    prefs.clear_cache()
    C._ollama_tags_cache = {
        "qwen3.8-27b-iq3s:latest",
        "qwen3-vl:8b-instruct",
        "nomic-embed-text:latest",
    }
    monkeypatch.setenv("CHAT_MODEL", "qwen3.8-27b-iq3s")
    monkeypatch.setenv("VISION_MODEL", "qwen3.8-27b-iq3s")
    monkeypatch.delenv("FRIDAY_MODEL_VISION", raising=False)
    monkeypatch.setattr(C, "VISION_MODEL", "qwen3.8-27b-iq3s")
    monkeypatch.setattr(C, "CHAT_MODEL", "qwen3.8-27b-iq3s")
    monkeypatch.setattr(C, "MODEL_NAME", "qwen3.8-27b-iq3s")
    assert C.resolve_vision_model() == "qwen3-vl:8b-instruct"
    C._ollama_tags_cache = None


def test_pref_chat_model_overrides_env(tmp_path, monkeypatch):
    import friday.runtime.prefs as prefs

    monkeypatch.setattr(prefs, "_path", lambda: tmp_path / "runtime_prefs.json")
    prefs.clear_cache()
    monkeypatch.setenv("CHAT_MODEL", "qwen3.5:9b")
    monkeypatch.setattr(C, "CHAT_MODEL", "qwen3.5:9b")
    prefs.update({"chat_model": "gemma4:12b"})
    assert C.resolve_chat_model() == "gemma4:12b"
    prefs.clear_cache()
