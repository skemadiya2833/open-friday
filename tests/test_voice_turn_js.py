"""Sanity-check conversational turn heuristics in web/public/turn.js (no browser)."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TURN = (ROOT / "web" / "public" / "turn.js").read_text(encoding="utf-8")


def test_turn_js_ships_and_mentions_sources():
    assert "FridayTurn" in TURN
    assert "semantic_vad" in TURN or "OpenAI" in TURN
    assert "completeness" in TURN
    assert "energyQuietMs" in TURN


def test_turn_js_loaded_before_app():
    html = (ROOT / "web" / "public" / "index.html").read_text(encoding="utf-8")
    i_turn = html.find("turn.js")
    i_app = html.find("app.js")
    assert i_turn > 0 and i_app > i_turn


def test_completeness_patterns_present():
    # Mirror key regex intent so refactors don't silently drop them.
    assert "TRAIL_OPEN" in TURN
    assert "SHORT_DONE" in TURN
    assert "IMPERATIVE" in TURN
    assert re.search(r"maxWaitMs:\s*3800", TURN)  # medium eagerness band
