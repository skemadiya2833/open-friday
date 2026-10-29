"""Presence skins, model aliases, capability clamp, humor banks."""

from __future__ import annotations

import re

from friday.assistant.intent import _deterministic_intent, _resolve_presence_intent
from friday.presence.modelswitch import (
    parse_switch_model_utterance,
    resolve_model_alias,
)
from friday.presence.registry import prompt_presence_block
from friday.presence.skins import CAPABILITY_CLAMP, SKINS, get_skin, resolve_skin_id
from friday.prompts import system_prompt


def test_all_skins_registered():
    for sid in ("friday", "jarvis", "ultron", "vision", "karen", "edith"):
        assert sid in SKINS
        skin = get_skin(sid)
        assert skin.style_delta
        assert skin.humor_bank
        assert skin.css_theme.startswith("skin-")


def test_resolve_skin_aliases():
    assert resolve_skin_id("jarvis") == "jarvis"
    assert resolve_skin_id("ultron mode") == "ultron"
    assert resolve_skin_id("F.R.I.D.A.Y.") == "friday"


def test_capability_clamp_in_prompt():
    block = prompt_presence_block(kind="chat")
    assert "Theatrical persona is performance only" in block
    assert "unauthorized access" in block
    text = system_prompt("chat")
    assert CAPABILITY_CLAMP.split(".")[0] in text or "Theatrical persona" in text


def test_observe_skips_skin_dump():
    assert prompt_presence_block(kind="observe") == ""


def test_ultron_style_is_theatrical_not_hacking():
    ultron = get_skin("ultron")
    low = ultron.style_delta.lower()
    assert "jokes" in low or "theatrical" in low or "inspired" in low
    assert (
        "must not" in CAPABILITY_CLAMP.lower() or "cannot" in CAPABILITY_CLAMP.lower()
    )


def test_humor_banks_have_no_film_quotes():
    banned = (
        "i am iron man",
        "avengers assemble",
        "stark industries",
        "i am inevitable",
        "with great power",
    )
    for skin in SKINS.values():
        blob = " ".join(skin.humor_bank).lower()
        for b in banned:
            assert b not in blob, f"{skin.id} bank contains {b!r}"


def test_intent_skin_switch():
    hit = _resolve_presence_intent("switch to jarvis")
    assert hit is not None
    assert hit.skill_id == "presence"
    det = _deterministic_intent("ultron mode")
    assert det is not None
    assert det.skill_id == "presence"


def test_intent_model_switch():
    hit = _resolve_presence_intent("switch to qwen")
    assert hit is not None
    assert hit.skill_id == "presence"
    assert parse_switch_model_utterance("switch to gemma") == "gemma"


def test_intent_camera_presence():
    hit = _resolve_presence_intent("camera presence on")
    assert hit is not None
    assert hit.skill_id == "presence"
    hit2 = _resolve_presence_intent("see me")
    assert hit2 is not None


def test_resolve_model_alias_picks_family():
    tags = ["llama3.2:3b", "qwen2.5:7b", "qwen2.5-vl:7b", "gemma4:12b"]
    assert resolve_model_alias("qwen", tags=tags) in {"qwen2.5-vl:7b", "qwen2.5:7b"}
    assert resolve_model_alias("gemma", tags=tags) == "gemma4:12b"
    assert resolve_model_alias("nope-model", tags=tags) is None


def test_skin_switch_does_not_change_tool_policy_text():
    """Clamp must appear for every skin; no skin grants extra powers in style_delta."""
    power = re.compile(r"(?i)bypass|override safety|disable approval|hack the|rootkit")
    for skin in SKINS.values():
        assert not power.search(skin.style_delta)
        assert CAPABILITY_CLAMP
