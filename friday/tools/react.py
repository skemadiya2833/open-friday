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
    r"stand by|working on (that|it)|"
    r"checking (my |the )?memory|searching memory"
    r")\b"
)
# Hollow answers the model invents instead of reporting tool results.
_HOLLOW_DONE = re.compile(
    r"(?i)^\s*("
    r"done\.?|"
    r"done[,.]?\s*(boss|friday)?\.?|"
    r"all (set|done)\.?|"
    r"consider it handled\.?|"
    r"ok\.?|okay\.?"
    r")\s*$"
)
# Claims research happened but cites nothing concrete (common after web_search).
_HOLLOW_RESEARCH = re.compile(
    r"(?i)\b("
    r"i('?ve| have) gathered (some )?(initial )?research|"
    r"here('?s| is) (some |my )?(initial )?(research|findings)|"
    r"based on (my |the )?(initial )?research|"
    r"to help with (our |your )?planning|"
    r"initial research on .{5,80} (to help|for (our|your))"
    r")\b"
)


def _required_lookup_tool(allowed_tools: list[str]) -> str | None:
    if "web_search" in allowed_tools:
        return "web_search"
    if "memory_search" in allowed_tools:
        return "memory_search"
    return None


def _is_hollow_done(text: str) -> bool:
    return bool(text and _HOLLOW_DONE.match(text.strip()))


def _is_hollow_research_brief(text: str) -> bool:
    """True when FINAL claims research but has no titles, URLs, or numbered hits."""
    t = (text or "").strip()
    if not t:
        return True
    if re.search(r"(?m)^\s*\d+\.\s+\S", t) or re.search(r"https?://\S", t):
        return False
    if re.search(r"(?i)\btop hits\s*:", t):
        return False
    if _HOLLOW_RESEARCH.search(t):
        return True
    # Trailing orphan bullet / colon with no substance.
    if len(t) < 220 and re.search(r"[:\*]\s*$", t):
        return True
    return False


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
        from friday.knowledge.search import clean_web_query

        q = clean_web_query(message) or re.sub(r"\s+", " ", (message or "").strip())[:200]
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
    from friday.prompts import react_brief_prompt, react_step_prompt

    overlay = with_plan_if_needed(system_overlay or system_prompt("agent"), message)

    hist = ""
    for turn in (history or [])[-6:]:
        hist += f"{turn.get('role','user').upper()}: {turn.get('content','')}\n"

    observations = ""
    final_reply = ""
    seen_calls: set[tuple[str, str]] = set()

    for step in range(steps):
        prompt = react_step_prompt(
            overlay=overlay,
            tools_block=tools_prompt_block(allowed_tools),
            hist=hist,
            message=message,
            observations=observations,
            step=step,
            steps=steps,
        )
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

        need = _required_lookup_tool(allowed_tools)
        must_tool = bool(need) and not tool_trace
        body = text[6:].strip() if text.upper().startswith("FINAL:") else text

        if text.upper().startswith("FINAL:"):
            if (
                must_tool
                or _is_tool_theater(body, allowed_tools=allowed_tools, tool_trace=tool_trace)
                or _is_hollow_done(body)
            ):
                tool_hint = need or "a tool"
                observations += (
                    f"\nDo not answer yet (and never say only 'Done'). "
                    f"Call {tool_hint} with a JSON tool call first, "
                    "then FINAL: from the observations.\n"
                )
                continue
            final_reply = body
            break

        if _is_tool_theater(body, allowed_tools=allowed_tools, tool_trace=tool_trace) or (
            must_tool and _is_hollow_done(body)
        ):
            tool_hint = need or "web_search"
            observations += (
                f"\nDo not narrate or say 'Done'. "
                f"Output a tool JSON call now ({tool_hint} with a precise query), "
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
            if name in {"web_search", "memory_search"}:
                observations += (
                    f"\nYou have the {name} results. Output FINAL: as a short briefing for the user. "
                    "Do not call that tool again. Never answer with only 'Done'.\n"
                )
            continue

        # Plain text with required lookup still unused → nudge, don't hang up on narration.
        if must_tool:
            observations += (
                f"\nCall {need} now (JSON tool call). Do not reply in plain text yet.\n"
            )
            continue

        if _is_hollow_done(text):
            observations += (
                "\nThat answer is empty. Call a tool or FINAL: with real content.\n"
            )
            continue

        final_reply = text
        break

    # Still no tools after the loop (model kept narrating / said Done) → force lookup once.
    need = _required_lookup_tool(allowed_tools)
    if (not tool_trace and need) or _is_hollow_done(final_reply or ""):
        if not tool_trace and need:
            forced = _force_first_tool(
                message, allowed_tools=allowed_tools, emit=emit, tool_trace=tool_trace
            )
            if forced:
                label = need
                brief_prompt = react_brief_prompt(
                    overlay=overlay,
                    message=message,
                    label=label,
                    observation=forced,
                )
                brief = query_model_text(brief_prompt, format_json=False, reasoning_mode=False)
                final_reply = (brief.get("message") or brief.get("raw") or "").strip()
                if final_reply.upper().startswith("FINAL:"):
                    final_reply = final_reply[6:].strip()
                if (
                    not final_reply
                    or _is_hollow_done(final_reply)
                    or _is_tool_theater(
                        final_reply, allowed_tools=allowed_tools, tool_trace=tool_trace
                    )
                ):
                    final_reply = _spoken_tool_result(need, forced)

    if not final_reply or final_reply.strip() in ("{}", "[]", "null") or _is_hollow_done(final_reply):
        if tool_trace:
            last = tool_trace[-1]
            final_reply = _spoken_tool_result(
                str(last.get("tool") or ""),
                str(last.get("result") or ""),
            )
        else:
            final_reply = _honest_react_fallback(message, allowed_tools=allowed_tools)

    # Never show raw tool JSON to the owner.
    if re.search(r'"tool"\s*:' , final_reply) or final_reply.strip().startswith("```"):
        if tool_trace:
            last = tool_trace[-1]
            final_reply = _spoken_tool_result(
                str(last.get("tool") or ""),
                str(last.get("result") or ""),
            )
        else:
            call = _extract_tool_call(final_reply)
            if call:
                name = str(call.get("tool"))
                args = call.get("args") if isinstance(call.get("args"), dict) else {k: v for k, v in call.items() if k != "tool"}
                out = call_tool_result(name, args, caller="react").text()
                tool_trace.append({"tool": name, "args": args, "result": out[:2000]})
                final_reply = _spoken_tool_result(name, out)
            else:
                final_reply = _honest_react_fallback(message, allowed_tools=allowed_tools)

    from friday.assistant.reply_guard import looks_like_prompt_dump

    if looks_like_prompt_dump(final_reply or ""):
        if tool_trace:
            last = tool_trace[-1]
            final_reply = _spoken_tool_result(
                str(last.get("tool") or ""),
                str(last.get("result") or ""),
            )
        else:
            final_reply = _honest_react_fallback(message, allowed_tools=allowed_tools)

    # After a real web_search, never leave theater ("I've gathered… *").
    web_hits = [t for t in tool_trace if t.get("tool") == "web_search"]
    if web_hits and _is_hollow_research_brief(final_reply or ""):
        final_reply = _spoken_tool_result(
            "web_search",
            str(web_hits[-1].get("result") or ""),
        )

    return final_reply, {"tools": tool_trace, "steps": len(transcript)}


def _honest_react_fallback(message: str, *, allowed_tools: list[str]) -> str:
    """Never say 'try once more' with nothing useful — read local state or ask one question."""
    from friday.persona import owner_name

    tools = set(allowed_tools or [])
    if "plan_list" in tools:
        try:
            out = call_tool_result("plan_list", {}, caller="react").text()
            spoken = _spoken_tool_result("plan_list", out)
            if spoken and not _is_hollow_done(spoken):
                return spoken
        except Exception:  # noqa: BLE001
            pass
    if "memory_search" in tools:
        try:
            q = (message or "").strip()[:120] or "recent"
            out = call_tool_result("memory_search", {"query": q}, caller="react").text()
            spoken = _spoken_tool_result("memory_search", out)
            if spoken and not _is_hollow_done(spoken):
                return spoken
        except Exception:  # noqa: BLE001
            pass
    return (
        f"I don't have a clean answer yet, {owner_name()}. "
        "Say that again with one more detail and I'll take it from there."
    )


def _spoken_tool_result(tool: str, raw: str) -> str:
    """Turn raw tool text into something speakable — never bare 'Done'."""
    from friday.persona import owner_name

    hit = (raw or "").strip()
    if tool == "schedule_task" and hit and not hit.startswith("{"):
        return f"Scheduled, {owner_name()}. I'll remind you when it's due."
    if tool == "plan_list":
        if not hit or "(no agenda" in hit.lower() or "no agenda items" in hit.lower():
            return (
                f"Board's clear for today, {owner_name()}. "
                "Say what to lock in and I'll put it on the agenda."
            )
        # Drop the "Today (date):" header for voice; keep bullet lines.
        lines = [
            re.sub(r"^[\s•\-\d.]+", "", ln).strip()
            for ln in hit.splitlines()
            if ln.strip() and not ln.lower().startswith("today (")
        ]
        body = "; ".join(x for x in lines if x)[:500]
        return f"On today's agenda: {body}." if body else hit[:500]
    if tool == "memory_search":
        if hit and not hit.lower().startswith("no "):
            # Strip score/id prefix lines into plain speech when possible.
            lines = []
            for line in hit.splitlines():
                m = re.match(r"^\s*-\s*\([^)]+\)\s*\[[^\]]+\]\s*(.+)$", line)
                lines.append((m.group(1) if m else line).strip())
            body = "; ".join(x for x in lines if x)[:700]
            return body or f"Nothing in memory on that, {owner_name()}."
        return f"Nothing in memory on that, {owner_name()}."
    if tool == "web_search":
        return _spoken_web_search(hit) if hit else f"Search came back empty, {owner_name()}."
    return hit[:900] if hit else f"I finished the step but had nothing useful to say, {owner_name()}."


def _spoken_web_search(raw: str) -> str:
    """Turn fenced search dumps into a short spoken list of titles."""
    from friday.persona import owner_name

    hit = (raw or "").strip()
    m = re.search(
        r"BEGIN_UNTRUSTED_DATA[^\n]*\n(.*)\nEND_UNTRUSTED_DATA",
        hit,
        re.S,
    )
    body = (m.group(1) if m else hit).strip()
    titles: list[str] = []
    for line in body.splitlines():
        mm = re.match(r"^\s*\d+\.\s+(.+)$", line)
        if mm:
            title = mm.group(1).strip()
            if title and not title.lower().startswith("[blocked"):
                titles.append(title)
    if titles:
        top = "; ".join(titles[:5])
        return f"Top hits: {top}."[:900]
    clean = re.sub(r"\s+", " ", body).strip()
    return clean[:900] if clean else f"Search came back empty, {owner_name()}."
