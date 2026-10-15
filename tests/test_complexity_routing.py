"""Stage V4: heuristic complexity routing (no learned router)."""

from __future__ import annotations

from friday.models.complexity import (
    resolve_routed_chat_model,
    score_complexity,
    select_chat_role,
)


def test_short_greeting_is_simple():
    r = score_complexity("hi")
    assert r.score <= 0.20
    assert select_chat_role("hi") == "fast"


def test_explain_why_routes_main():
    q = "Explain why local models matter for privacy, step by step."
    assert select_chat_role(q) == "main"
    assert score_complexity(q).score > 0.20


def test_code_routes_main():
    assert select_chat_role("fix this def foo(): pass") == "main"


def test_routing_opt_in_default_off(monkeypatch):
    monkeypatch.delenv("FRIDAY_COMPLEXITY_ROUTING", raising=False)
    monkeypatch.setenv("FRIDAY_MODEL_FAST", "qwen3.5:4b")
    monkeypatch.setenv("FRIDAY_MODEL_MAIN", "qwen3.5:9b")
    monkeypatch.setattr("friday.models.complexity.complexity_routing_enabled", lambda: False)
    tag, meta = resolve_routed_chat_model("hi")
    assert meta["complexity_routing"] is False
    assert "9b" in tag


def test_routing_opt_in_simple_to_4b(monkeypatch):
    """When routing is explicitly on and FAST is set to 4b, simple queries use 4b."""
    monkeypatch.setenv("FRIDAY_MODEL_FAST", "qwen3.5:4b")
    monkeypatch.setenv("FRIDAY_MODEL_MAIN", "qwen3.5:9b")
    monkeypatch.setenv("FRIDAY_MODEL_ROLES", "false")
    monkeypatch.setattr("friday.models.complexity.complexity_routing_enabled", lambda: True)
    tag, meta = resolve_routed_chat_model("hi")
    assert meta["complexity_routing"] is True
    assert meta["role"] == "fast"
    assert tag == "qwen3.5:4b"


def test_urgency_forces_fast(monkeypatch):
    monkeypatch.setattr("friday.models.complexity.complexity_routing_enabled", lambda: True)
    assert select_chat_role("explain everything about quantum computing", urgency=0.9) == "fast"


def test_fast_defaults_to_main_9b(monkeypatch):
    """Owner default: no second model — FAST inherits MAIN (9b)."""
    monkeypatch.delenv("FRIDAY_MODEL_FAST", raising=False)
    monkeypatch.setenv("FRIDAY_MODEL_MAIN", "qwen3.5:9b")
    from friday.models.roles import get_model_roles

    roles = get_model_roles()
    assert roles.fast == roles.main == "qwen3.5:9b"
