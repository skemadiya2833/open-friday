"""Local model talk must never become web research fanfic."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_bare_qwen_tag_is_presence_not_research():
    from friday.assistant.intent import classify_intent
    from friday.presence.modelswitch import looks_like_model_switch, looks_like_model_talk

    for msg in (
        "qwen3.8",
        "Qwen3.8",
        "qwen 3.5 9b",
        "switch to qwen3.8",
        "install qwen3.8",
        "use qwen3.8 for vision",
    ):
        assert looks_like_model_talk(msg), msg
        assert looks_like_model_switch(msg), msg
        intent = classify_intent(msg)
        assert intent.skill_id == "presence", (msg, intent.skill_id, intent.reason)
        assert intent.skill_id != "research", msg


def test_model_lore_query_stays_presence():
    from friday.assistant.intent import classify_intent

    msg = "was qwen3.8 turned down by alibaba and rebranded as saluki"
    intent = classify_intent(msg)
    assert intent.skill_id == "presence"
