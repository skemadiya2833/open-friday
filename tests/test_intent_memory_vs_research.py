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
        "bring some design references",
        "find me UI inspiration for a dark dashboard",
        "show design references for a landing page",
    ):
        intent = classify_intent(msg)
        assert intent.skill_id == "research", msg
        assert intent.mode == "research", msg


def test_vague_search_asks_for_topic():
    for msg in (
        "can you do a little search for me",
        "do a quick search",
        "search something for me",
        "look something up",
        "can you research for me",
    ):
        intent = classify_intent(msg)
        assert intent.mode == "clarify", msg
        assert intent.skill_id == "chat", msg
        assert "topic" in intent.objective.lower() or "search" in intent.objective.lower(), msg


def test_topic_after_clarify_runs_research():
    history = [
        {"role": "user", "content": "can you do a little search for me"},
        {
            "role": "assistant",
            "content": "What should I search for — give me a topic or question.",
        },
    ]
    intent = classify_intent("best filament for outdoor 3d prints", history=history)
    assert intent.skill_id == "research"
    assert intent.mode == "research"
    assert "filament" in intent.objective.lower()


def test_yeah_do_that_research_uses_assistant_offer_not_greeting():
    """Regression: confirm must not google 'hey friday what's going on'."""
    history = [
        {"role": "user", "content": "Hey Friday what's going on"},
        {
            "role": "assistant",
            "content": (
                "Board’s clear, boss. Unless you want me to run that 3D printing research now."
            ),
        },
    ]
    for msg in ("Yeah do that research", "Do that research", "Yeah do that"):
        intent = classify_intent(msg, history=history)
        assert intent.skill_id == "research", msg
        assert intent.mode == "research", msg
        assert "3d printing" in intent.objective.lower(), (msg, intent.objective)
        assert "going on" not in intent.objective.lower(), (msg, intent.objective)


def test_search_with_topic_not_swallowed_by_confirm():
    history = [
        {"role": "user", "content": "Hey Friday what's going on"},
        {"role": "assistant", "content": "Board’s clear."},
    ]
    intent = classify_intent(
        "Search for the best ways to become a good assistant",
        history=history,
    )
    assert intent.skill_id == "research"
    assert "confirm" not in intent.reason
    assert "assistant" in intent.objective.lower()
