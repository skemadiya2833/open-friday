"""Research replies must stay human — no prompt theater, reuse related prior hits."""

from __future__ import annotations

import time

from friday.assistant.reply_guard import looks_like_prompt_dump
from friday.knowledge.search import find_related_search, format_results, reset_cache, _cache
from friday.tools.react import _is_hollow_research_brief, _spoken_web_search
from friday.types import KnowledgeNote


def test_user_goal_theater_is_dump():
    text = (
        "* User's goal: Research ideas for 3D printable products\n"
        "* Constraint 1: Research for real\n"
        "*Correction*: The prompt says tell the user…"
    )
    assert looks_like_prompt_dump(text)
    assert _is_hollow_research_brief(text)


def test_empty_search_format_has_no_prompt_coaching():
    out = format_results("bone models", [])
    assert "could not reach" not in out.lower()
    assert "tell the user" not in out.lower()
    spoken = _spoken_web_search(out)
    assert "user's goal" not in spoken.lower()
    assert "search" in spoken.lower()


def test_related_prior_search_reuse():
    reset_cache()
    _cache["3d printing bone structure physiotherapist"] = (
        time.time(),
        KnowledgeNote(query="3d printing bone structure", summary="ok", source="web_search"),
        [{"title": "Bone models for PT", "url": "http://x", "snippet": "s"}],
    )
    got = find_related_search(
        "Bring up ideas on 3D printing for physiotherapist doctors bone structure"
    )
    assert got is not None
    assert got[0] == "3d printing bone structure"
    assert got[1][0]["title"].startswith("Bone")
