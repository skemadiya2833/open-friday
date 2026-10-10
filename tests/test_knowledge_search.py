from friday.knowledge import search as KS
from friday.knowledge.search import format_results, perform_knowledge_search, reset_cache


def setup_function() -> None:
    reset_cache()


def test_search_returns_headlines_not_a_tab_note(monkeypatch):
    monkeypatch.setattr(
        KS,
        "fetch_web_results",
        lambda q, **k: [{"title": "City floods overnight", "snippet": "Times", "url": "https://n.example/1"}],
    )
    note = perform_knowledge_search("today's news")
    assert "City floods overnight" in note.summary
    assert "Opened a search tab" not in note.summary
    assert "Brief the user" in note.summary


def test_same_query_is_not_fetched_twice(monkeypatch):
    n = {"c": 0}

    def fetch(q, **k):
        n["c"] += 1
        return [{"title": "A", "snippet": "B", "url": ""}]

    monkeypatch.setattr(KS, "fetch_web_results", fetch)
    perform_knowledge_search("same query")
    perform_knowledge_search("Same   Query")
    assert n["c"] == 1


def test_format_empty_tells_the_model_not_to_open_tabs():
    text = format_results("x", [])
    assert "do not open more tabs" in text.lower()


def test_news_lookup_is_research_not_desktop():
    from friday.assistant.intent import classify_intent

    for msg in ("what's the news", "search today's headlines", "look up who won", "how's the weather today"):
        intent = classify_intent(msg)
        assert intent.skill_id == "research", msg
        assert intent.mode == "research"


def test_react_skips_duplicate_web_search(monkeypatch):
    from friday.tools import react as R
    import friday.models.local as loc

    calls = {"n": 0}

    def fake_query(prompt, **k):
        calls["n"] += 1
        if calls["n"] <= 2:
            return {"message": '```json\n{"tool":"web_search","args":{"query":"news"}}\n```'}
        return {"message": "FINAL: Floods in the city overnight."}

    class FakeOut:
        def text(self) -> str:
            return "1. City floods overnight"

    monkeypatch.setattr(loc, "query_model_text", fake_query)
    monkeypatch.setattr(R, "get_model_manager", lambda: type("M", (), {"ensure_loaded": lambda self, x: None})())
    monkeypatch.setattr(R, "call_tool_result", lambda *a, **k: FakeOut())
    monkeypatch.setattr(R, "tools_prompt_block", lambda tools: "web_search")
    reply, meta = R.run_react("what's the news", allowed_tools=["web_search"], max_steps=4)
    tools = [t["tool"] for t in meta["tools"]]
    assert tools.count("web_search") == 1
    assert "Floods" in reply or "floods" in reply.lower()
