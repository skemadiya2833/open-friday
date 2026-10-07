"""Bounded ReAct-lite loop using Ollama text responses + JSON tool calls."""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from friday.config import MAX_TOOL_STEPS
from friday.models.manager import get_model_manager
from friday.tools.registry import call_tool_result, tools_prompt_block

_TOOL_RE = re.compile(
    r"```(?:json)?\s*(\{.*?\})\s*```|(\{[^{}]*\"tool\"\s*:\s*\"[^\"]+\"[^{}]*\})",
    re.S,
)


def _extract_tool_call(text: str) -> dict[str, Any] | None:
    for match in _TOOL_RE.finditer(text):
        raw = match.group(1) or match.group(2)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("tool"):
            return data
    # bare line: TOOL_CALL {"tool":"...","args":{}}
    m = re.search(r"TOOL_CALL\s*(\{.*\})", text, re.S)
    if m:
        try:
            data = json.loads(m.group(1))
            if data.get("tool"):
                return data
        except json.JSONDecodeError:
            pass
    return None


def run_react(
    message: str,
    *,
    allowed_tools: list[str],
    system_overlay: str = "",
    history: list[dict[str, str]] | None = None,
    emit: Callable[[str, dict[str, Any]], None] | None = None,
    max_steps: int | None = None,
) -> tuple[str, dict[str, Any]]:
    from friday.models.local import query_model_text

    emit = emit or (lambda *_: None)
    get_model_manager().ensure_loaded("chat")
    steps = max_steps or MAX_TOOL_STEPS
    transcript: list[str] = []
    tool_trace: list[dict[str, Any]] = []

    hist = ""
    for turn in (history or [])[-6:]:
        hist += f"{turn.get('role','user').upper()}: {turn.get('content','')}\n"

    observations = ""
    final_reply = ""

    for step in range(steps):
        prompt = f"""{system_overlay}

You are Friday's tool-using skill. You may call ONE tool per step OR give a final answer.

Available tools:
{tools_prompt_block(allowed_tools)}

To call a tool, output ONLY a JSON object in a fenced block:
```json
{{"tool": "name", "args": {{...}}}}
```

To finish, output plain text starting with FINAL: then your answer for the user.

Conversation:
{hist}
USER: {message}
{observations}
Step {step + 1}/{steps}. Decide.
"""
        result = query_model_text(prompt, format_json=False, reasoning_mode=False)
        text = (result.get("message") or result.get("raw") or "").strip()
        transcript.append(text)
        emit("thinking_token", {"token": text[:400]})

        if text.upper().startswith("FINAL:"):
            final_reply = text[6:].strip()
            break

        call = _extract_tool_call(text)
        if call:
            name = str(call.get("tool"))
            args = call.get("args") if isinstance(call.get("args"), dict) else {}
            # Also accept flat args
            if not args:
                args = {k: v for k, v in call.items() if k != "tool"}
            emit("tool_call", {"tool": name, "args": args})
            # Model output (possibly shaped by untrusted screen/web text) goes through
            # policy + approval + audit; it is never executed directly.
            out = call_tool_result(name, args, caller="react").text()
            emit("tool_result", {"tool": name, "result": out[:1000]})
            tool_trace.append({"tool": name, "args": args, "result": out[:2000]})
            observations += f"\nObservation from {name}:\n{out}\n"
            continue

        # No tool call — treat entire response as final
        final_reply = text
        break

    if not final_reply:
        if tool_trace:
            last = tool_trace[-1]
            final_reply = last.get("result") or "Done."
            if last.get("tool") == "schedule_task" and not last.get("result", "").startswith("{"):
                final_reply = "Scheduled, boss. I'll remind you when it's due."
        else:
            final_reply = "I could not complete that request."

    # Never show raw tool JSON to the owner.
    if re.search(r'"tool"\s*:' , final_reply) or final_reply.strip().startswith("```"):
        if tool_trace:
            final_reply = tool_trace[-1].get("result") or "Done, boss."
        else:
            call = _extract_tool_call(final_reply)
            if call:
                name = str(call.get("tool"))
                args = call.get("args") if isinstance(call.get("args"), dict) else {k: v for k, v in call.items() if k != "tool"}
                out = call_tool_result(name, args, caller="react").text()
                tool_trace.append({"tool": name, "args": args, "result": out[:2000]})
                final_reply = out
            else:
                final_reply = "Done, boss."

    return final_reply, {"tools": tool_trace, "steps": len(transcript)}
