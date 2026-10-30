"""Varying num_ctx on the hot chat/vision tag reloads Ollama — pin one size."""

from __future__ import annotations


def test_stable_num_ctx_ignores_per_call_overrides_for_hot_tag():
    from friday.config import resolve_chat_model, resolve_resident_num_ctx
    from friday.models.local import _stable_num_ctx

    hot = resolve_chat_model()
    resident = resolve_resident_num_ctx()
    assert _stable_num_ctx(hot, 1536) == resident
    assert _stable_num_ctx(hot, 4096) == resident
    assert _stable_num_ctx(hot, None) == resident


def test_agent_prompt_stays_lean():
    from friday.prompts import AGENT, system_prompt

    assert "Never invent tool results" in AGENT
    assert "What you do:" not in AGENT  # full CORE ballast removed from tool loop
    assert len(AGENT) < 700
    text = system_prompt("agent")
    assert "Never invent tool results" in text
    assert "What you do:" not in text
