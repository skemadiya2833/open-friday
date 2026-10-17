"""Vision must not send screenshots to a text-only GGUF."""

from __future__ import annotations

from friday import config as C


def test_text_gguf_detected():
    assert C._name_looks_text_only("qwen3.8-27b-iq3s")
    assert not C._name_looks_vision("qwen3.8-27b-iq3s")


def test_vl_tag_detected():
    assert C._name_looks_vision("qwen3-vl:8b-instruct")
    assert not C._name_looks_text_only("qwen3-vl:8b-instruct")


def test_resolve_vision_falls_back_from_iq3(monkeypatch):
    C._ollama_tags_cache = {
        "qwen3.8-27b-iq3s:latest",
        "qwen3-vl:8b-instruct",
        "nomic-embed-text:latest",
    }
    monkeypatch.setenv("CHAT_MODEL", "qwen3.8-27b-iq3s")
    monkeypatch.setenv("VISION_MODEL", "qwen3.8-27b-iq3s")
    monkeypatch.delenv("FRIDAY_MODEL_VISION", raising=False)
    # Re-read module-level defaults aren't refreshed — call with patched getenv via resolve.
    monkeypatch.setattr(C, "VISION_MODEL", "qwen3.8-27b-iq3s")
    monkeypatch.setattr(C, "CHAT_MODEL", "qwen3.8-27b-iq3s")
    monkeypatch.setattr(C, "MODEL_NAME", "qwen3.8-27b-iq3s")
    assert C.resolve_vision_model() == "qwen3-vl:8b-instruct"
    C._ollama_tags_cache = None
