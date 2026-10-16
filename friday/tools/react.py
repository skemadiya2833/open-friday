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

# Model roleplays "Searching the web…" instead of calling a tool — reject as FINAL.
_TOOL_THEATER = re.compile(
    r"(?i)\b("
    r"searching (the )?(web|internet|online|for)|"
    r"looking (that |it |this )?(up|into)|"
    r"let me (search|look|check|find|pull|browse)|"
    r"i('?ll| will) (search|look|check|find|pull|browse|open)|"
    r"i('?m| am) (searching|looking|checking|pulling|browsing)|"
    r"hold on|one (sec|moment|second)|give me a (sec|moment|second)|"
    r"pulling (that |it )?up|checking (the web|online|that now)|"
    r"stand by|working on (that|it)"
    r")\b"
)


def _is_tool_theater(text: str, *, allowed_tools: list[str], tool_trace: list) -> bool:
    """True when the model narrates work but no tool has run yet."""
    if tool_trace or not text:
        return False
    if not _TOOL_THEATER.search(text):
        return False
    return bool(allowed_tools)


def _force_first_tool(
    message: str,
    *,
    allowed_tools: list[str],
    emit: Callable[[str, dict[str, Any]], None],
    tool_trace: list[dict[str, Any]],
) -> str | None:
    """Last-resort: run web_search (or memory_search) from the user ask."""
    if "web_search" in allowed_tools:
        q = re.sub(r"\s+", " ", (message or "").strip())[:200]
        if not q:
            return None
        emit("tool_call", {"tool": "web_search", "args": {"query": q}})
        out = call_tool_result("web_search", {"query": q}, caller="react").text()
        emit("tool_result", {"tool": "web_search", "result": out[:1000]})
        tool_trace.append({"tool": "web_search", "args": {"query": q}, "result": out[:2000]})
        return out
    if "memory_search" in allowed_tools:
        q = re.sub(r"\s+", " ", (message or "").strip())[:200]
        emit("tool_call", {"tool": "memory_search", "args": {"query": q}})
        out = call_tool_result("memory_search", {"query": q}, caller="react").text()
        emit("tool_result", {"tool": "memory_search", "result": out[:1000]})
        tool_trace.append({"tool": "memory_search", "args": {"query": q}, "result": out[:2000]})
        return out
    return None


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

    from friday.agent.behavior import with_plan_if_needed
    from friday.persona import system_prompt

    overlay = with_plan_if_needed(system_overlay or system_prompt("agent"), message)

    hist = ""
    for turn in (history or [])[-6:]:
        hist += f"{turn.get('role','user').upper()}: {turn.get('content','')}\n"

    observations = ""
    final_reply = ""
    seen_calls: set[tuple[str, str]] = set()

    for step in range(steps):
        prompt = f"""{overlay}

You are Friday operating tools on the owner's machine. Call ONE tool per step, or finish with FINAL:.
Prefer doing the work over explaining how you would do it.

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
        from friday.models.roles import TOOL_CALL_SCHEMA

        # Structured outputs: prefer a tool JSON object; plain FINAL: replies still work if the
        # model ignores the schema (Ollama may return {} — we fall through to text parsing).
        result = query_model_text(
            prompt,
            format_json=False,
            format_schema=TOOL_CALL_SCHEMA,
            reasoning_mode=False,
        )
        text = (result.get("message") or result.get("raw") or "").strip()
        # Structured-output models sometimes return {} / empty — don't treat as a final answer.
        if not text or text in ("{}", "[]", "null"):
            observations += (
                "\n(Empty model output.) Call a tool if needed, or output FINAL: with a short answer.\n"
            )
            continue
        transcript.append(text)
        emit("thinking_token", {"token": text[:400]})

        must_tool = ("web_search" in allowed_tools) and not tool_trace
        body = text[6:].strip() if text.upper().startswith("FINAL:") else text

        if text.upper().startswith("FINAL:"):
            if must_tool or _is_tool_theater(
                body, allowed_tools=allowed_tools, tool_trace=tool_trace
            ):
                observations += (
                    "\nDo not answer yet. Call web_search with a JSON tool call first, "
                    "then FINAL: from the observations.\n"
                )
                continue
            final_reply = body
            break

        if _is_tool_theater(body, allowed_tools=allowed_tools, tool_trace=tool_trace):
            observations += (
                "\nDo not narrate searching or looking things up. "
                "Output a tool JSON call now (web_search with a precise query), "
                "then FINAL: only after you have observations.\n"
            )
            continue

        call = _extract_tool_call(text)
        if call:
            name = str(call.get("tool"))
            args = call.get("args") if isinstance(call.get("args"), dict) else {}
            # Also accept flat args
            if not args:
                args = {k: v for k, v in call.items() if k != "tool"}
            sig = (name, json.dumps(args, sort_keys=True, default=str)[:800])
            if sig in seen_calls:
                observations += (
                    "\nYou already ran that exact tool. Do not call it again. "
                    "Output FINAL: with the answer from the observations above.\n"
                )
                continue
            seen_calls.add(sig)
            emit("tool_call", {"tool": name, "args": args})
            # Model output (possibly shaped by untrusted screen/web text) goes through
            # policy + approval + audit; it is never executed directly.
            out = call_tool_result(name, args, caller="react").text()
            emit("tool_result", {"tool": name, "result": out[:1000]})
            tool_trace.append({"tool": name, "args": args, "result": out[:2000]})
            observations += f"\nObservation from {name}:\n{out}\n"
            if name == "web_search":
                observations += (
                    "\nYou have the search results. Output FINAL: as a briefing for the user. "
                    "Do not search again.\n"
                )
            continue

        # Plain text with web_search still unused → nudge, don't hang up on narration.
        if must_tool:
            observations += (
                "\nCall web_search now (JSON tool call). Do not reply in plain text yet.\n"
            )
            continue

        final_reply = text
        break

    # Still no tools after the loop (model kept narrating) → search once, then brief.
    if not tool_trace and "web_search" in allowed_tools:
        forced = _force_first_tool(
            message, allowed_tools=allowed_tools, emit=emit, tool_trace=tool_trace
        )
        if forced:
            brief_prompt = (
                f"{overlay}\n\nUSER: {message}\n\nObservation from web_search:\n{forced}\n\n"
                "Output FINAL: as a short briefing of what you found. No more tools."
            )
            brief = query_model_text(brief_prompt, format_json=False, reasoning_mode=False)
            final_reply = (brief.get("message") or brief.get("raw") or "").strip()
            if final_reply.upper().startswith("FINAL:"):
                final_reply = final_reply[6:].strip()
            if (
                not final_reply
                or _is_tool_theater(
                    final_reply, allowed_tools=allowed_tools, tool_trace=tool_trace
                )
            ):
                final_reply = forced[:900]

    if not final_reply or final_reply.strip() in ("{}", "[]", "null"):
        if tool_trace:
            last = tool_trace[-1]
            final_reply = last.get("result") or "Done."
            if last.get("tool") == "schedule_task" and not last.get("result", "").startswith("{"):
                from friday.persona import owner_name

                final_reply = f"Scheduled, {owner_name()}. I'll remind you when it's due."
            elif last.get("tool") == "memory_search":
                from friday.persona import owner_name

                hit = (last.get("result") or "").strip()
                final_reply = (
                    hit
                    if hit and not hit.lower().startswith("no ")
                    else f"Nothing in memory on that, {owner_name()}."
                )
            elif last.get("tool") == "web_search":
                final_reply = last.get("result") or final_reply
        else:
            from friday.persona import owner_name

            final_reply = f"I couldn't finish that cleanly, {owner_name()}. Try once more."

    # Never show raw tool JSON to the owner.
    if re.search(r'"tool"\s*:' , final_reply) or final_reply.strip().startswith("```"):
        if tool_trace:
            from friday.persona import owner_name

            final_reply = tool_trace[-1].get("result") or f"Done, {owner_name()}."
        else:
            call = _extract_tool_call(final_reply)
            if call:
                name = str(call.get("tool"))
                args = call.get("args") if isinstance(call.get("args"), dict) else {k: v for k, v in call.items() if k != "tool"}
                out = call_tool_result(name, args, caller="react").text()
                tool_trace.append({"tool": name, "args": args, "result": out[:2000]})
                final_reply = out
            else:
                from friday.persona import owner_name

                final_reply = f"Done, {owner_name()}."

    return final_reply, {"tools": tool_trace, "steps": len(transcript)}
