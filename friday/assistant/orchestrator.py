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

    if voice_mode:
        emit("activity", {"step": "voice", "message": "Voice mode · keeping answers short"})

    # --- Architectural gate: LLM classify + deterministic policy ---
    emit("status", {"status": "thinking"})
    emit("activity", {"step": "classify", "message": "Figuring out what you want…"})
    intent = classify_intent(
        message,
        history=history,
        override_skill=skill_override,
    )
    emit("intent", intent.to_dict())
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

    # Clarify mode: answer with a question, don't dispatch tools blindly.
    if intent.mode == "clarify":
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
    want_rag = (
        CHAT_RAG_ENABLED
        or intent.skill_id == "memory"
        or intent.mode == "remember"
        or bool(_RAG_HINT.search(message))
    )
    if want_rag:
        try:
            from friday.memory import get_memory

            for h in get_memory().search(message, collection="memories", limit=3):
                if h.score >= 0.3:
                    mem_hits.append(h.text)
        except Exception as exc:
            emit("warning", {"message": f"memory unavailable: {exc}"})

    # Always give chat/skills a light view of today's open agenda.
    try:
        from friday.tasks.plan import format_for_prompt, get_plan

        plan = get_plan()
        open_items = [it for it in (plan.get("items") or []) if not it.get("done")]
        if open_items:
            mem_hits.insert(
                0,
                "TODAY'S PLAN:\n" + format_for_prompt(),
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
        "computer_use": "Controlling the desktop…",
        "memory": "Checking memory…",
        "research": "Researching…",
        "files": "Working with files…",
        "tasks": "Scheduling…",
    }
    emit("activity", {
        "step": "skill_run",
        "message": skill_labels.get(intent.skill_id, f"Running {intent.skill_id}…"),
    })
    if intent.skill_id == "computer_use":
        emit("status", {"status": "acting"})
    elif intent.skill_id == "observe":
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
    # Voice mode: keep spoken replies punchy even if a skill was wordy.
    reply = result.reply
    if voice_mode and reply:
        reply = _clip_voice_reply(reply)
    emit("activity", {"step": "done", "message": "Done"})
    emit("status", {"status": "idle"})

    if result.skill_id == "computer_use" and result.metadata.get("status") == "completed":
        try:
            from friday.memory import get_memory
            get_memory().add(
                f"Completed desktop task: {skill_message}",
                metadata={"source": "computer_use"},
            )
        except Exception:
            pass

    store.append(session, "assistant", reply, skill_id=result.skill_id)
    return {
        "reply": reply,
        "session_id": session.id,
        "skill_id": result.skill_id,
        "events": events,
        "metadata": {**(result.metadata or {}), "intent": intent.to_dict(), "voice_mode": voice_mode},
    }


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
