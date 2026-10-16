"""Reject 'Searching the web…' theater — force a real tool call."""

from __future__ import annotations

from unittest.mock import patch

from friday.tools import react as R


def test_is_tool_theater_detects_searching_line():
    assert R._is_tool_theater(
        "Searching the web for guides on personal assistants…",
        allowed_tools=["web_search"],
        tool_trace=[],
    )
    assert not R._is_tool_theater(
        "Here are three solid guides on assistants.",
        allowed_tools=["web_search"],
        tool_trace=[],
    )
    assert not R._is_tool_theater(
        "Searching the web…",
        allowed_tools=["web_search"],
        tool_trace=[{"tool": "web_search"}],
    )


def test_run_react_forces_search_when_model_narrates():
    calls = {"n": 0}

    def fake_model(prompt, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"message": "Searching the web for guides on assistants."}
        return {"message": "FINAL: Three short tips from the results."}

    class _TR:
        def text(self):
            return "1. Prefer action\n2. Confirm risky clicks\n3. Use tools"

    with patch("friday.models.manager.get_model_manager") as gm:
        gm.return_value.ensure_loaded = lambda *_a, **_k: None
        with patch("friday.models.local.query_model_text", side_effect=fake_model):
            with patch("friday.tools.react.call_tool_result", return_value=_TR()):
                reply, meta = R.run_react(
                    "find guides on being a good assistant",
                    allowed_tools=["web_search"],
                    system_overlay="research",
                    max_steps=3,
                )
    assert "web_search" in {t.get("tool") for t in meta.get("tools") or []}
    assert "Searching the web" not in reply
    assert "tips" in reply.lower() or "Prefer action" in reply or "results" in reply.lower()
