"""Chat must not wrap history as a labeled transcript (dump magnet)."""

from __future__ import annotations

from friday.skills.builtin.chat import handler as H


def test_history_messages_skips_glitch_and_dumps():
    hist = [
        {"role": "user", "content": "what's going on"},
        {"role": "assistant", "content": "I glitched on that, boss. Say it once more?"},
        {"role": "user", "content": "research brands"},
        {
            "role": "assistant",
            "content": "Role: Friday\nContext: The user is asking about brands.",
        },
        {"role": "user", "content": "ok"},
        {"role": "assistant", "content": "Board's live — brand research is next."},
    ]
    msgs = H._history_messages(hist)
    texts = [m["content"] for m in msgs]
    assert not any("glitched" in t.lower() for t in texts)
    assert not any(t.startswith("Role:") for t in texts)
    assert any("Board's live" in t for t in texts)
    assert msgs[-1]["role"] == "assistant"


def test_honest_fallback_never_says_glitched():
    out = H._honest_fallback("Did you pull up those 3D printing ideas", "boss")
    assert "glitched" not in out.lower()
    assert "research" in out.lower() or "look" in out.lower()


def test_prior_research_ask_routes_to_research():
    from friday.assistant import intent as I

    got = I._deterministic_intent(
        "Did you pull up those Uh 3D printing a business ideas and like setuping"
    )
    assert got is not None
    assert got.skill_id == "research"
