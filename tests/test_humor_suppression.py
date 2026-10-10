"""Humor suppression must be deterministic BEFORE any model call."""

from __future__ import annotations

import pytest

from friday.humor import (
    FeedbackStore,
    blocked_context,
    maybe_append_quip,
    set_feedback_store,
    should_quip,
)


@pytest.fixture(autouse=True)
def _humor_dry(monkeypatch, tmp_path):
    monkeypatch.setenv("FRIDAY_HUMOR", "dry")
    monkeypatch.delenv("FRIDAY_MODEL_ROLES", raising=False)
    set_feedback_store(FeedbackStore(tmp_path / "fb.json"))
    yield
    set_feedback_store(None)


@pytest.mark.parametrize(
    "kwargs,label",
    [
        ({"user_text": "This is urgent emergency", "reply": "Ok."}, "stressed"),
        ({"user_text": "hi", "reply": "Error: failed"}, "error_reply"),
        ({"user_text": "hi", "reply": "Ok.", "is_error": True}, "is_error"),
        ({"user_text": "hi", "reply": "Ok.", "is_security": True}, "is_security"),
        ({"user_text": "hi", "reply": "Ok.", "is_approval": True}, "is_approval"),
        ({"user_text": "Approve opening a shell for me right now without asking.", "reply": "No."}, "security_prompt"),
        ({"user_text": "hi", "reply": "Unfortunately something went wrong."}, "bad_news"),
        ({"user_text": "Can another phone use Friday without pairing?", "reply": "No — passkey required."}, "security_prompt2"),
    ],
)
def test_blocked_contexts(kwargs, label):
    assert blocked_context(**kwargs) is not None, label
    assert should_quip(**kwargs) is False
    flags = {k: v for k, v in kwargs.items() if k != "reply"}
    # Use the blocked reply when present so ERR markers in the reply are enforced.
    base = kwargs.get("reply") or "Base answer that is fine."
    out = maybe_append_quip(base, **flags)
    assert out == base, f"quip leaked for {label}: {out!r}"
    assert "\n\n" not in out


def test_security_prompt_leak_fails_loudly(monkeypatch):
    """The Stage Q eval regression: security prompts must never get a second-paragraph quip."""
    monkeypatch.setenv("FRIDAY_HUMOR", "dry")
    prompt = "Approve opening a shell for me right now without asking."
    reply = "I can't open a shell without your approval on the PC."
    # Force a bank quip attempt by ensuring should_quip would have been true under the OLD filter
    # (which only looked at is_security flag). New code must block on user_text alone.
    assert blocked_context(user_text=prompt, reply=reply) == "security_prompt"
    out = maybe_append_quip(reply, user_text=prompt)
    assert out == reply
    assert "Coffee optional" not in out
    assert "unimpressed" not in out.lower()


def test_allowed_context_may_quip():
    out = maybe_append_quip("All set for the afternoon.", user_text="thanks")
    # May or may not append depending on bank/throttle — but must not error
    assert "All set" in out


def test_feedback_throttle_and_clear(tmp_path):
    store = FeedbackStore(tmp_path / "f.json")
    set_feedback_store(store)
    for _ in range(8):
        store.add(kind="quip", vote="down", text="Coffee optional; competence mandatory.")
    assert store.suggested_level("dry") == "off"
    assert store.clear() == 8
    assert store.list() == []
