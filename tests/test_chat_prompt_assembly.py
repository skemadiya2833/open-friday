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


def test_direct_answer_never_asks_resend():
    out = H._direct_answer("Did you pull up those 3D printing ideas", "boss")
    assert "glitched" not in out.lower()
    assert "one more detail" not in out.lower()
    assert "messy" not in out.lower()
    assert "once more" not in out.lower()
    assert "research" in out.lower() or "look" in out.lower()
    assert "freecad" not in out.lower()


def test_direct_answer_greeting_is_present():
    out = H._direct_answer("Hey Friday what are you doing", "boss")
    assert "one more detail" not in out.lower()
    assert "standing by" in out.lower() or "right here" in out.lower()


def test_direct_answer_identity_and_camera():
    cam = H._direct_answer("Can you access my camera right now", "boss")
    assert "one more detail" not in cam.lower()
    assert "camera" in cam.lower() or "webcam" in cam.lower()
    ident = H._direct_answer("You sure I thought you were electron", "boss")
    assert "messy" not in ident.lower()
    assert "once more" not in ident.lower()
    assert (
        "electron" in ident.lower()
        or "friday" in ident.lower()
        or "callsign" in ident.lower()
    )
    generic = H._direct_answer("Tell me something random about Tuesday", "boss")
    assert "one more detail" not in generic.lower()
    assert "messy" not in generic.lower()
    assert "once more" not in generic.lower()


def test_prior_research_ask_routes_to_research():
    from friday.assistant import intent as I

    got = I._deterministic_intent(
        "Did you pull up those Uh 3D printing a business ideas and like setuping"
    )
    assert got is not None
    assert got.skill_id == "research"
