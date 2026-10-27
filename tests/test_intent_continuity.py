"""Project continuity must not become a pointless web search."""

from __future__ import annotations

from friday.assistant.intent import _deterministic_intent


def test_continue_robot_project_is_chat():
    msg = (
        "Uh tell me some Other task that we could do like maybe we could "
        "continue on our robot Tech like the esp22 one and the taskbot companion"
    )
    got = _deterministic_intent(msg)
    assert got is not None
    assert got.skill_id == "chat"
    assert got.mode == "talk"
    assert "continuity" in got.reason or "brainstorm" in got.reason


def test_how_to_get_setup_is_chat_or_cad():
    got = _deterministic_intent("how can i get this setup finished")
    assert got is not None
    assert got.skill_id in ("chat", "cad")
    assert got.skill_id != "research"
