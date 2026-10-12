"""Forget one / forget all covers every Memory Core collection, not just owner notes."""

from friday.assistant.session import ConversationSession, ConversationTurn, SessionStore
from friday.memory.forget import forget_entry


def test_forget_conversation_turn(tmp_path, monkeypatch):
    monkeypatch.setattr("friday.assistant.session.CONVERSATIONS_DIR", str(tmp_path))
    store = SessionStore()
    s = ConversationSession(id="abc", title="t", turns=[ConversationTurn(role="user", content="hi", ts=1.5)])
    store.save(s)
    monkeypatch.setattr("friday.assistant.session.get_session_store", lambda: store)
    assert forget_entry("conversations", "abc:1.5")
    assert store.load("abc").turns == []


def test_forget_plan_item(tmp_path, monkeypatch):
    monkeypatch.setattr("friday.tasks.plan.DATA_DIR", str(tmp_path))
    from friday.tasks.plan import add_item, get_plan

    item = add_item("buy milk")
    assert forget_entry("plan", item["id"])
    assert get_plan()["items"] == []
