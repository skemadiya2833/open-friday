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

    # Skills receive the rewritten objective when Act/Research follow-ups rewrote the goal
    # (e.g. "yeah do that" → "3D printing market"). Bare user text stays for normal turns.
    skill_message = message
    if intent.mode == "act" and (intent.objective or "").strip():
        skill_message = intent.objective
    elif (
        intent.skill_id == "research"
        and (intent.objective or "").strip()
        and intent.objective.strip() != message.strip()
        and not intent.objective.lower().startswith("what should i search")
    ):
        skill_message = intent.objective
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
    # Chat sometimes roleplays work, invents cloud limits / fake PC specs, or asks the owner to run shell.
    # Never force-reroute a bare greeting into web research ("Hey Friday" ≠ Wikipedia).
    from friday.assistant.reflexes import _is_greeting_only

    force_action = (
        result.skill_id == "chat"
        and not _is_greeting_only(message)
        and (
            _fake_action_promise(result.reply or "", message)
            or _false_capability_denial(result.reply or "")
            or _asks_owner_to_run_shell(result.reply or "")
            or _fake_hardware_report(result.reply or "")
        )
    )
    if force_action:
        objective, skill_name = _recover_action_objective(message, history, result.reply or "")
        # Greeting / empty callsign recovered as research → keep the chat reply instead.
        if skill_name == "research" and _is_greeting_only(objective):
            skill_name = ""
        target = get_registry().get(skill_name) if skill_name else None
        if target is not None:
            want_report = skill_name == "research" and bool(
                re.search(
                    r"(?i)\b(research|report|references?|inspiration|compare|dossier|deep dive)\b",
                    f"{message} {objective}",
                )
            )
            emit(
                "activity",
                {
                    "step": "reroute",
                    "message": (
                        "Actually doing it…"
                        if skill_name == "computer_use"
                        else "Actually looking that up…"
                    ),
                },
            )
            emit("status", {"status": "acting" if skill_name == "computer_use" else "thinking"})
            result = target.run(
                SkillContext(
                    message=objective,
                    session_id=session.id,
                    history=history,
                    memory_hits=mem_hits,
                    skill_override=skill_name,
                    voice_mode=voice_mode,
                    emit=emit,
                    metadata={"report_mode": want_report, "forced_from_chat": True},
                )
            )
    # Voice mode: keep spoken replies punchy even if a skill was wordy.
    reply = (result.reply or "").strip()
    if not reply:
        # Never hand the UI an empty string — voice treats that as "(no reply)" and re-arms the mic.
        reply = (
            "I finished the step but have nothing solid to report yet. "
            "Say what you want next and I'll take it."
        )
    if voice_mode and reply:
        reply = _clip_voice_reply(reply)
    if not voice_mode:
        emit("activity", {"step": "done", "message": "Done"})
    emit("status", {"status": "idle"})

    # Desktop completions stay in the session / experience store — do not dump
    # every task string into vector memory.
    _maybe_diary(result.skill_id, message, reply, result.metadata or {})
    turn_meta = {
        k: result.metadata.get(k)
        for k in (
            "report_id",
            "open_report",
            "open_findings",
            "fallback_plain",
            "error",
            "tools",
            "learned",
        )
        if result.metadata and k in result.metadata
    }
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
                "meta": turn_meta,
                "events": [
                    {"type": e.get("type"), "message": (e.get("message") or e.get("status") or "")[:120]}
                    for e in events[-12:]
                    if isinstance(e, dict)
                ],
            }
        )
    except Exception:  # noqa: BLE001
        pass

    turn_id = ""
    try:
        from friday.runtime.training_log import log_training_turn

        turn_id = log_training_turn(
            user=message,
            reply=reply,
            skill=result.skill_id,
            intent=intent.to_dict(),
            session_id=session.id,
            voice=voice_mode,
            meta=turn_meta,
        )
    except Exception:  # noqa: BLE001
        pass

    store.append(session, "assistant", reply, skill_id=result.skill_id)
    return {
        "reply": reply,
        "session_id": session.id,
        "skill_id": result.skill_id,
        "events": events,
        "metadata": {
            **(result.metadata or {}),
            "intent": intent.to_dict(),
            "voice_mode": voice_mode,
            "turn_id": turn_id,
        },
    }


_FAKE_PROMISE = re.compile(
    r"(?i)\b("
    r"i('?ll| will) (pull|bring|look|open|get|fetch|search|find|launch|navigate)|"
    r"let me (pull|bring|look|open|get|fetch|search|find|launch)|"
    r"i('?m| am) (opening|launching|pulling|searching|looking|navigating)|"
    r"opening (a |the |your )?(browser|chrome|powershell|tab|window|site)|"
    r"stand by|holding on|one (sec|moment|second)|give me a moment|"
    r"pulling that up|looking that up|on (it|your screen)|"
    r"consider it handled|queued in powershell|browser is open|search query is queued|"
    r"i'll take care|working on that now|"
    r"running system hardware|executing|\*\u2026executing\*\u2026|"
    r"hardware summary|no spoofing|just your hardware"
    r")\b"
)

# Chat invents boutique PC builds (4090 / i7-12700K / DDR4-3200) instead of measuring.
_FAKE_HARDWARE = re.compile(
    r"(?i)\b("
    r"i7-?\s*12700k|rtx\s*4090|ddr4\s*@\s*3200|core i[3579]-|"
    r"ran\s+`?systeminfo`?|ran\s+`?wmic`?|ran\s+`?dxdiag`?|"
    r"no spoofing,\s*no guesswork"
    r")\b"
)

# Model roleplays as a limited cloud bot — nonsense on a local Friday install.
_FALSE_CAPABILITY = re.compile(
    r"(?i)\b("
    r"i can'?t browse( external)?( websites?)?|"
    r"cannot browse( external)?( websites?)?|"
    r"unable to browse|"
    r"don'?t have (real-?time |live )?access to (the )?(web|internet|websites?|documents?)|"
    r"can'?t read documents in real-?time|"
    r"internal knowledge base|"
    r"as an ai (language )?model|"
    r"i don'?t have (the )?ability to (browse|search|open|read files)"
    r")\b"
)

# Asks the owner to run a shell command and paste output — Friday should run it herself.
_ASK_USER_SHELL = re.compile(
    r"(?i)\b("
    r"run\b.{0,80}\b(wmic|powershell|cmd|get-ciminstance|get-wmiobject)\b|"
    r"open powershell and (run|execute)|"
    r"tell me what it (lists|says|returns|shows)|"
    r"paste (the |that )?(output|result)|"
    r"i('?ll| will) interpret (the )?(output|result)"
    r")\b"
)


def _fake_action_promise(reply: str, user: str) -> bool:
    """True when chat promised desktop/web work but no tool skill ran."""
    if not reply or not _FAKE_PROMISE.search(reply):
        return False
    # Any fake promise from chat is enough — confirmations like "yes do that" have no lookup verbs.
    return True


def _false_capability_denial(reply: str) -> bool:
    """True when chat invents cloud-assistant limits Friday does not have."""
    return bool(reply and _FALSE_CAPABILITY.search(reply))


def _asks_owner_to_run_shell(reply: str) -> bool:
    """True when chat tells the owner to run PowerShell/WMIC instead of doing it."""
    return bool(reply and _ASK_USER_SHELL.search(reply))


def _fake_hardware_report(reply: str) -> bool:
    """True when chat invents a hardware dump instead of measuring this PC."""
    return bool(reply and _FAKE_HARDWARE.search(reply))


def _recover_action_objective(
    message: str, history: list[dict[str, str]], reply: str
) -> tuple[str, str]:
    """Pick a real objective + skill when chat faked an action or capability denial."""
    from friday.assistant.intent import _last_substantive_user

    prior = _last_substantive_user(history) or message
    blob = f"{message} {prior} {reply}".lower()
    if _fake_hardware_report(reply) or re.search(
        r"\b(system ?specs?|hardware|gpu|vram|ram|cpu|disk|nvme)\b",
        blob,
    ):
        # Always re-measure — never trust chat's invented bill of materials.
        return "check system hardware", "computer_use"
    if re.search(
        r"\b(monitor|display|camera|webcam|peripheral|device|usb|wmic|hardware|screen)\b",
        blob,
    ):
        return prior, "computer_use"
    if re.search(r"\b(click|type|notepad|desktop|screen|chrome|browser|powershell|open)\b", blob):
        # Prefer research for web lookups; computer_use when clearly desktop.
        if re.search(r"\b(reference|website|sites?|search|google|article|learn|research)\b", blob):
            return prior, "research"
        if re.search(r"\b(click|type|notepad|desktop|drag|save file)\b", blob):
            return prior, "computer_use"
        return prior, "research"
    if re.search(
        r"\b(article|learn|research|search|google|website|reference|document|checklist)\b",
        blob,
    ):
        return prior, "research"
    # Default: desktop act only when the reply clearly promised UI work; else research
    # — but never for callsign-only / greeting leftovers.
    from friday.assistant.reflexes import _is_greeting_only

    if _is_greeting_only(message) or _is_greeting_only(prior):
        return message, "chat"
    return prior, "research"


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
        # Always close the stream with a spoken reply — empty done → voice "blanked" loop.
        yield {
            "type": "done",
            "reply": f"That failed on my side: {holder['error']}",
            "session_id": session_id,
            "skill_id": None,
            "metadata": {"error": holder["error"]},
        }
        return
    result = holder.get("result") or {}
    reply = (result.get("reply") or "").strip() or (
        "I finished the step but have nothing solid to report yet. Say what you want next."
    )
    meta = result.get("metadata") or {}
    yield {
        "type": "done",
        "reply": reply,
        "session_id": result.get("session_id"),
        "skill_id": result.get("skill_id"),
        "turn_id": meta.get("turn_id") or "",
        "metadata": meta,
    }
