"""Memory recall must not fall into web research; bare search ≠ google."""

from __future__ import annotations

from friday.assistant.intent import classify_intent


def test_search_memory_routes_to_memory():
    for msg in (
        "Search up your memory again and tell me what do you find",
        "can you search your memory for quarterly reports",
        "check your memory — did I mention any reports",
        "what do you remember about today",
    ):
        intent = classify_intent(msg)
        assert intent.skill_id == "memory", msg
        assert intent.mode == "remember", msg
        assert "memory" in intent.reason


def test_web_search_still_research():
    for msg in (
        "search the web for rust async book",
        "google the weather in London",
        "look up the latest news on OLED",
        "what's the weather today",
    ):
        intent = classify_intent(msg)
        assert intent.skill_id == "research", msg
        assert intent.mode == "research", msg
