"""Research skill — short briefing or structured report pipeline."""

from __future__ import annotations

import re

from friday.skills.base import Skill, SkillContext, SkillManifest, SkillResult

_REPORT = re.compile(
    r"\b(research report|deep research|full report|structured report|"
    r"write (me )?a report|think (through|about)|compare .+ (vs|versus|and))\b",
    re.I,
)
_OPEN = re.compile(r"\bopen (the |my )?(research )?report\b", re.I)
_LEARN = re.compile(
    r"\b("
    r"learn (from|about|how)|study (how|about)|read (up )?(on|about)|"
    r"read articles|absorb|internalize|"
    r"teach yourself|research and (learn|remember|memorize)"
    r")\b",
    re.I,
)


def _learn_from_web(topic: str, emit) -> SkillResult:
    """Search → distill principles → durable doctrine + memory (for future actions)."""
    from friday.knowledge.search import fetch_web_results, format_results
    from friday.models.local import query_model_text
    from friday.persona import owner_name
    from friday.runtime import doctrine as DOC

    q = re.sub(
        r"(?i)\b(please|friday|learn|study|read( articles)?|about|how to|for me)\b",
        " ",
        topic,
    )
    q = re.sub(r"\s+", " ", q).strip() or topic
    search_q = q if len(q) > 8 else f"how to {topic}"
    emit("activity", {"step": "learn", "message": f"Studying · {search_q[:80]}"})
    rows = fetch_web_results(search_q, limit=6)
    if not rows:
        return SkillResult(
            reply=f"I couldn't reach search to study that, {owner_name()}. Try again in a moment.",
            skill_id="research",
            metadata={"learned": False},
        )
    brief = format_results(search_q, rows)
    prompt = (
        "Distill lasting operating principles for a local PC AI assistant from these search hits.\n"
        f"Topic: {search_q}\n\n{brief}\n\n"
        "Return JSON only: {\"topic\": string, \"lessons\": [5 to 8 short imperative bullets], "
        "\"tldr\": one sentence}. No fluff. Lessons must be actionable on a desktop assistant."
    )
    out = query_model_text(prompt, format_json=True, num_predict=700, num_ctx=4096)
    raw = out.get("message") or out.get("raw") or {}
    if isinstance(raw, str):
        import json

        try:
            raw = json.loads(raw)
        except Exception:  # noqa: BLE001
            raw = {}
    lessons = [str(x).strip() for x in (raw.get("lessons") or []) if str(x).strip()]
    topic_label = str(raw.get("topic") or search_q)[:120]
    tldr = str(raw.get("tldr") or "").strip()
    if len(lessons) < 3:
        # Fallback: use titles/snippets as soft lessons
        lessons = [
            (r.get("snippet") or r.get("title") or "")[:200]
            for r in rows[:5]
            if (r.get("snippet") or r.get("title"))
        ]
    sources = [r.get("url") or "" for r in rows if r.get("url")]
    rec = DOC.add_lessons(topic_label, lessons, sources=sources)
    # Also pin a single memory blob for semantic recall.
    try:
        from friday.memory import get_memory

        blob = (
            f"Doctrine · {topic_label}: "
            + "; ".join(rec.get("bullets") or lessons)[:900]
        )
        get_memory().add(blob, metadata={"kind": "doctrine", "topic": topic_label})
    except Exception as exc:  # noqa: BLE001
        print(f"[Research] doctrine memory write failed: {exc}")
    n = len(rec.get("bullets") or lessons)
    spoken = tldr or f"Studied {topic_label} — kept {n} principles for next time."
    spoken = f"{spoken} I'll apply them on future turns, {owner_name()}."
    return SkillResult(
        reply=spoken,
        skill_id="research",
        metadata={
            "learned": True,
            "topic": topic_label,
            "lessons": n,
            "sources": sources[:4],
        },
    )


class SkillHandler(Skill):
    manifest = SkillManifest(
        id="research",
        name="Research",
        description="Web research and structured reports",
        tools=["web_search", "memory_search"],
        system_overlay=(
            "You look things up for the owner. Call web_search ONCE with a precise query FIRST. "
            "Never say 'Searching the web…' or 'Looking that up…' as your answer — that is not a tool call. "
            "The observation is the actual results — titles and snippets. Then output FINAL: "
            "as a short briefing of what you found (what happened, who, when). "
            "Never search the same query twice. Never mention tabs or Google. "
            "If results are empty, say so in FINAL:; do not keep searching."
        ),
    )

    def run(self, ctx: SkillContext) -> SkillResult:
        msg = ctx.message or ""
        try:
            from friday.runtime.blackout import blocks_research
            from friday.persona import owner_name

            if blocks_research():
                return SkillResult(
                    reply=(
                        f"Blackout is on, {owner_name()} — web research is paused. "
                        "Turn it off in Systems → Safety, or ask me something I can answer from local memory."
                    ),
                    skill_id="research",
                    metadata={"blackout": True},
                )
        except Exception:  # noqa: BLE001
            pass
        if _OPEN.search(msg):
            from friday.reports.store import list_reports

            rows = list_reports(limit=1)
            if not rows:
                return SkillResult(
                    reply="I don't have a report on file yet. Ask me to research something first.",
                    skill_id="research",
                    metadata={"open_report": None},
                )
            rid = rows[0]["id"]
            return SkillResult(
                reply="Opening the latest report on screen.",
                skill_id="research",
                metadata={"open_report": rid},
            )

        if _LEARN.search(msg):
            return _learn_from_web(msg, ctx.emit)

        # Visual / reference hunts → quick HTML brief (search + gallery), not chat theater.
        want_refs = bool(
            re.search(
                r"\b(references?|inspiration|examples?|mood ?boards?|design\s+refs?)\b",
                msg,
                re.I,
            )
        )
        want_report = (
            bool(_REPORT.search(msg))
            or want_refs
            or (ctx.metadata or {}).get("report_mode")
        )
        mode = "quick"
        if re.search(r"\bdeep\b", msg, re.I):
            mode = "deep"
        if re.search(r"\bthink\b", msg, re.I) and not re.search(r"\bdeep\b", msg, re.I):
            mode = "think"
        if want_report:
            from friday.humor import maybe_append_quip
            from friday.persona import owner_name
            from friday.reports.pipeline import run_research_report

            def _emit(typ: str, payload=None, **kw):
                data = dict(payload or {})
                data.update(kw)
                ctx.emit(f"report_{typ}", data)  # type: ignore[arg-type]

            doc = run_research_report(msg, mode=mode, emit=_emit)
            tldr = (doc.get("summary") or {}).get("tldr") or "Report ready."
            spoken = (
                f"{tldr} The full report is on screen, {owner_name()}."
            )
            spoken = maybe_append_quip(
                spoken,
                user_text=msg,
                is_error=bool(doc.get("fallback_plain")),
                is_security=False,
            )
            return SkillResult(
                reply=spoken,
                skill_id="research",
                metadata={
                    "report_id": doc.get("id"),
                    "mode": mode,
                    "fallback_plain": bool(doc.get("fallback_plain")),
                    "open_report": doc.get("id"),
                    "claims": len(doc.get("claims") or []),
                },
            )

        from friday.tools.react import run_react

        reply, meta = run_react(
            ctx.message,
            allowed_tools=self.manifest.tools or ["web_search", "memory_search"],
            system_overlay=self.manifest.system_overlay,
            history=ctx.history,
            emit=ctx.emit,
        )
        return SkillResult(reply=reply, skill_id="research", metadata=meta)
