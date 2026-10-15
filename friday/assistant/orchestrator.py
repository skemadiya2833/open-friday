"""Top-level assistant: Intent brain → skill → persist."""

from __future__ import annotations

import queue
import re
import threading
from typing import Any, Callable, Iterator

from friday.assistant.intent import classify_intent
from friday.assistant.session import get_session_store
from friday.config import CHAT_RAG_ENABLED
from friday.skills.base import SkillContext
from friday.skills.registry import get_registry

_RAG_HINT = re.compile(
    r"\b(remember|recall|what did i|did i tell you|my preference|notes?\b)\b",
    re.I,
)


def _emit_factory(sink: list[dict[str, Any]], callback: Callable[[str, dict], None] | None):
    def emit(event: str, data: dict[str, Any]) -> None:
        payload = {"type": event, **data}
        sink.append(payload)
        if callback:
            callback(event, data)
    return emit


def handle_message(
    message: str,
    *,
    session_id: str | None = None,
    skill_override: str | None = None,
    voice_mode: bool = False,
    on_event: Callable[[str, dict], None] | None = None,
) -> dict[str, Any]:
    store = get_session_store()
    session = store.get_or_create(session_id)
    store.append(session, "user", message)

    events: list[dict[str, Any]] = []
    emit = _emit_factory(events, on_event)

    history = [{"role": t.role, "content": t.content} for t in session.turns[:-1]]

    if re.search(r"\b(clear|wipe|forget|reset)\b.{0,20}\b(chat|conversation|this (chat|conversation|link))\b", message, re.I):
        n = len(session.turns)
        session.turns = []
        session.title = "New chat"
        store.save(session)
        from friday.persona import owner_name

        reply = f"Chat cleared, {owner_name()}. Fresh page — durable memories stay in Memory Core."
        store.append(session, "assistant", reply, skill_id="chat")
        emit("status", {"status": "idle"})
        emit("chat_cleared", {"cleared": n})
        return {
            "reply": reply,
            "session_id": session.id,
            "skill_id": "chat",
            "events": events,
            "metadata": {"cleared": n},
        }

    # Durable facts + light knowledge — background so voice is not blocked.
    try:
        from friday.assistant.automemory import remember

        for fact in remember(message, background=True):
            emit("memory_saved", {"text": fact})
            emit("activity", {"step": "memory", "message": f"Remembered · {fact[:80]}"})
    except Exception as exc:  # noqa: BLE001
        print(f"[Memory] auto-remember failed: {exc}")
    try:
        from friday.runtime.knowledge import observe as kg_observe

        threading.Thread(
            target=lambda: kg_observe(message),
            daemon=True,
            name="FridayKnowledge",
        ).start()
    except Exception:  # noqa: BLE001
        pass

    # System-1 reflexes — skip the model for solved phrases (perf).
    if not skill_override:
        try:
            from friday.assistant.reflexes import try_reflex

            hit = try_reflex(message)
            if hit:
                emit("status", {"status": "idle"})
                emit("activity", {"step": "reflex", "message": f"Reflex · {hit.label}"})
                store.append(session, "assistant", hit.reply, skill_id=hit.skill_id)
                return {
                    "reply": hit.reply,
                    "session_id": session.id,
                    "skill_id": hit.skill_id,
                    "events": events,
                    "metadata": {"reflex": hit.label, "cached": hit.cached, "voice_mode": voice_mode},
                }
        except Exception as exc:  # noqa: BLE001
            print(f"[Reflex] skipped: {exc}")

    # --- Architectural gate: LLM classify + deterministic policy ---
    emit("status", {"status": "thinking"})
    # Voice stays quiet — no classify/intent chatter in the live HUD.
    if not voice_mode:
        emit("activity", {"step": "classify", "message": "Figuring out what you want…"})
    intent = classify_intent(
        message,
        history=history,
        override_skill=skill_override,
    )
    emit("intent", intent.to_dict())
    if not voice_mode:
        emit("activity", {
            "step": "intent",
            "message": (
                f"Mode · {intent.mode} → {intent.skill_id} "
                f"({intent.confidence:.0%} · {intent.source})"
            ),
            "detail": intent.reason,
        })
    emit("skill_selected", {
        "skill_id": intent.skill_id,
        "score": intent.confidence,
        "reason": f"{intent.mode}: {intent.reason}",
        "mode": intent.mode,
        "source": intent.source,
        "alternatives": [],
    })

    # Low-confidence Act → ask instead of grabbing the mouse.
    if intent.needs_confirmation and intent.mode == "act":
        reply = (
            f"Should I control the desktop for: {intent.objective}? Say yes or rephrase."
            if voice_mode
            else (
                f"I think you want me to control the desktop for:\n"
                f"**{intent.objective}**\n\n"
                f"Reply **yes** to run computer-use, or rephrase the task."
            )
        )
        store.append(session, "assistant", reply, skill_id="chat")
        emit("status", {"status": "idle"})
        return {
            "reply": reply,
            "session_id": session.id,
            "skill_id": "chat",
            "events": events,
            "metadata": {"awaiting_confirmation": True, "intent": intent.to_dict()},
        }

    # Clarify mode: ask one question — unless the classifier meant a real skill
    # (e.g. memory recall). Speaking the objective as the answer caused "search memory…"
    # to be read aloud instead of running memory_search.
    if intent.mode == "clarify":
        if intent.skill_id in {"memory", "research", "tasks", "files", "observe", "camera", "computer_use"}:
            from friday.assistant.intent import Intent as _Intent

            mode_for = {
                "memory": "remember",
                "research": "research",
                "tasks": "schedule",
                "files": "files",
                "observe": "look",
                "camera": "look",
                "computer_use": "act",
            }.get(intent.skill_id, "talk")
            intent = _Intent(
                mode=mode_for,  # type: ignore[arg-type]
                skill_id=intent.skill_id,
                confidence=intent.confidence,
                objective=message,
                reason=f"clarify→{intent.skill_id}",
                source=intent.source,
            )
        else:
            reply = intent.objective if intent.objective != message else (
                "Should I look at your screen, chat, or control the desktop?"
                if voice_mode
                else (
                    "I want to help — should I just look at your screen, chat about it, "
                    "or actually control the desktop (open/click/type)?"
                )
            )
            store.append(session, "assistant", reply, skill_id="chat")
            emit("status", {"status": "idle"})
            return {
                "reply": reply,
                "session_id": session.id,
                "skill_id": "chat",
                "events": events,
                "metadata": {"intent": intent.to_dict()},
            }

    mem_hits: list[str] = []
    try:
        from friday.assistant.automemory import owner_facts

        mem_hits.extend(owner_facts(8))
    except Exception:
        pass
    want_rag = (
        CHAT_RAG_ENABLED
        or intent.skill_id == "memory"
        or intent.mode == "remember"
        or bool(_RAG_HINT.search(message))
    )
    if want_rag:
        try:
            from friday.memory import get_memory

            for h in get_memory().search(message, collection="memories", limit=4):
                if h.score >= 0.25 and h.text not in mem_hits:
                    mem_hits.append(h.text)
        except Exception as exc:
            emit("warning", {"message": f"memory unavailable: {exc}"})

    # Today's agenda lines the owner saved — NOT open files, NOT permission to invent docs.
    try:
        from friday.tasks.plan import format_for_prompt, get_plan

        plan = get_plan()
        open_items = [it for it in (plan.get("items") or []) if not it.get("done")]
        if open_items:
            mem_hits.insert(
                0,
                "TODAY'S PLAN (owner-saved agenda text only — these are not desktop files, "
                "reports, or auditor threads; never invent documents or statuses from them):\n"
                + format_for_prompt(),
            )
    except Exception:
        pass

    skill = get_registry().get(intent.skill_id) or get_registry().get("chat")
    if skill is None:
        reply = "No skills are loaded."
        store.append(session, "assistant", reply)
        emit("status", {"status": "idle"})
        return {"reply": reply, "session_id": session.id, "skill_id": None, "events": events}

    # Skills receive the rewritten objective when Act; otherwise the user text.
    skill_message = intent.objective if intent.mode == "act" else message
    skill_labels = {
        "chat": "Chatting…",
        "observe": "Looking at your screen…",
        "camera": "Looking through the camera…",
        "computer_use": "Controlling the desktop…",
        "memory": "Checking memory…",
        "research": "Researching…",
        "files": "Working with files…",
        "tasks": "Scheduling…",
    }
    skill_msg = skill_labels.get(intent.skill_id, f"Running {intent.skill_id}…")
    # Live voice: only surface look/act — "Scheduling…" etc. belongs off-HUD.
    if not voice_mode or intent.skill_id in ("observe", "camera", "computer_use"):
        emit("activity", {"step": "skill_run", "message": skill_msg})
    # computer_use sets "acting" only after tools-first fails (see skill handler).
    if intent.skill_id in ("observe", "camera", "computer_use"):
        emit("status", {"status": "thinking"})

    ctx = SkillContext(
        message=skill_message,
        session_id=session.id,
        history=history,
        memory_hits=mem_hits,
        skill_override=skill_override,
        voice_mode=voice_mode,
        emit=emit,
    )
    result = skill.run(ctx)
    # Chat sometimes roleplays "I'll pull that up" without tools — force research once.
    if result.skill_id == "chat" and _fake_action_promise(result.reply or "", message):
        research = get_registry().get("research")
        if research is not None:
            emit("activity", {"step": "reroute", "message": "Actually looking that up…"})
            emit("status", {"status": "thinking"})
            result = research.run(
                SkillContext(
                    message=message,
                    session_id=session.id,
                    history=history,
                    memory_hits=mem_hits,
                    skill_override="research",
                    voice_mode=voice_mode,
                    emit=emit,
                    metadata={"report_mode": True},
                )
            )
    # Voice mode: keep spoken replies punchy even if a skill was wordy.
    reply = (result.reply or "").strip()
    if not reply:
        # Never hand the UI an empty string — voice treats that as "(no reply)" and re-arms the mic.
        reply = (
            "I finished that step but had nothing useful to say out loud. "
            "Try once more, or check the desktop."
        )
    if voice_mode and reply:
        reply = _clip_voice_reply(reply)
    if not voice_mode:
        emit("activity", {"step": "done", "message": "Done"})
    emit("status", {"status": "idle"})

    # Desktop completions stay in the session / experience store — do not dump
    # every task string into vector memory.
    _maybe_diary(result.skill_id, message, reply, result.metadata or {})
    try:
        from friday.runtime.debug_log import log_turn

        log_turn(
            {
                "session_id": session.id,
                "voice": voice_mode,
                "user": message,
                "intent": intent.to_dict(),
                "skill": result.skill_id,
                "reply": reply,
                "meta": {
                    k: result.metadata.get(k)
                    for k in ("report_id", "open_report", "fallback_plain", "error", "tools")
                    if result.metadata and k in result.metadata
                },
                "events": [
                    {"type": e.get("type"), "message": (e.get("message") or e.get("status") or "")[:120]}
                    for e in events[-12:]
                    if isinstance(e, dict)
                ],
            }
        )
    except Exception:  # noqa: BLE001
        pass

    store.append(session, "assistant", reply, skill_id=result.skill_id)
    return {
        "reply": reply,
        "session_id": session.id,
        "skill_id": result.skill_id,
        "events": events,
        "metadata": {**(result.metadata or {}), "intent": intent.to_dict(), "voice_mode": voice_mode},
    }


_FAKE_PROMISE = re.compile(
    r"(?i)\b("
    r"i('?ll| will) (pull|bring|look|open|get|fetch|search|find)|"
    r"let me (pull|bring|look|open|get|fetch|search|find)|"
    r"stand by|holding on|one (sec|moment|second)|"
    r"pulling that up|looking that up|on (it|your screen)"
    r")\b"
)
_ASKS_LOOKUP = re.compile(
    r"(?i)\b(references?|inspiration|examples?|research|look ?up|search|google|"
    r"find|bring|show|pull up|fetch|news|weather)\b"
)


def _fake_action_promise(reply: str, user: str) -> bool:
    """True when chat promised a lookup/action but no tool skill ran."""
    if not reply or not _FAKE_PROMISE.search(reply):
        return False
    return bool(_ASKS_LOOKUP.search(user or ""))


def _maybe_diary(skill_id: str, message: str, reply: str, meta: dict) -> None:
    """Log notable work to the day diary (not every chat turn)."""
    try:
        from friday.runtime.prefs import get as pref

        if not pref("diary"):
            return
    except Exception:  # noqa: BLE001
        return
    notable = skill_id in {"computer_use", "research", "tasks", "files", "camera"}
    if not notable and not meta.get("report_id") and not meta.get("reminder"):
        return
    try:
        from friday.runtime.diary import record

        title = (message or "").strip().replace("\n", " ")[:100] or skill_id
        body = (reply or "").strip().replace("\n", " ")[:240]
        record(title, body, kind=skill_id)
    except Exception:  # noqa: BLE001
        pass


def _clip_voice_reply(text: str, max_chars: int = 420) -> str:
    """Hard cap for spoken answers — prefer first 2–3 sentences."""
    clean = re.sub(r"\s+", " ", text.replace("**", "").strip())
    parts = re.split(r"(?<=[.!?])\s+", clean)
    short = " ".join(parts[:3]).strip()
    if len(short) > max_chars:
        short = short[: max_chars - 1].rsplit(" ", 1)[0] + "…"
    return short or clean[:max_chars]


def stream_message(
    message: str,
    *,
    session_id: str | None = None,
    skill_override: str | None = None,
    voice_mode: bool = False,
) -> Iterator[dict[str, Any]]:
    """Yield SSE events live (including token chunks) as the model generates."""
    q: queue.Queue[dict[str, Any] | None] = queue.Queue()
    holder: dict[str, Any] = {}

    def on_event(event: str, data: dict) -> None:
        q.put({"type": event, **data})

    def worker() -> None:
        try:
            holder["result"] = handle_message(
                message,
                session_id=session_id,
                skill_override=skill_override,
                voice_mode=voice_mode,
                on_event=on_event,
            )
        except Exception as exc:
            holder["error"] = str(exc)
            q.put({"type": "error", "message": str(exc)})
        finally:
            q.put(None)

    threading.Thread(target=worker, name="FridayChatStream", daemon=True).start()
    while True:
        item = q.get()
        if item is None:
            break
        yield item

    if "error" in holder:
        return
    result = holder.get("result") or {}
    yield {
        "type": "done",
        "reply": result.get("reply", ""),
        "session_id": result.get("session_id"),
        "skill_id": result.get("skill_id"),
        "metadata": result.get("metadata") or {},
    }
