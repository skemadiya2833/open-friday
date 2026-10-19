"""Research skill — short briefing or structured report pipeline."""

from __future__ import annotations

import re

from friday.prompts import OVERLAY_RESEARCH
from friday.skills.base import Skill, SkillContext, SkillManifest, SkillResult

_REPORT = re.compile(
    r"\b(research report|deep research|full report|structured report|"
    r"write (me )?a report|think (through|about)|compare .+ (vs|versus|and))\b",
    re.I,
)
_OPEN = re.compile(r"\bopen (the |my )?(research )?report\b", re.I)
_SHOW_FINDINGS = re.compile(
    r"(?i)^\s*("
    r"open research findings( on screen)?|"
    r"open (the )?(research )?findings|"
    r"show (last |the )?(research|findings|results)( on (my |the )?screen)?"
    r")\s*$"
)
_LEARN = re.compile(
    r"\b("
    r"learn (from|about|how)|study (how|about)|read (up )?(on|about)|"
    r"read articles|absorb|internalize|"
    r"teach yourself|research and (learn|remember|memorize)"
    r")\b",
    re.I,
)


def _open_latest_report() -> SkillResult | None:
    from friday.persona import owner_name

    try:
        from friday.reports.store import list_reports

        rows = list_reports(limit=1)
        if not rows:
            return None
        rid = rows[0]["id"]
        return SkillResult(
            reply=f"Opening the latest report on screen, {owner_name()}.",
            skill_id="research",
            metadata={"open_report": rid},
        )
    except Exception:  # noqa: BLE001
        return None


def _open_last_search_html() -> SkillResult | None:
    from friday.persona import owner_name
    from friday.knowledge.search import last_search_payload

    payload = last_search_payload()
    if not payload:
        return None
    query, hits, _summary = payload
    try:
        path = _write_findings_html(query, hits)
    except Exception as exc:  # noqa: BLE001
        return SkillResult(
            reply=f"Couldn't open the findings on screen: {exc}",
            skill_id="research",
            metadata={"open_findings": False, "error": str(exc)},
        )
    n = len(hits)
    return SkillResult(
        reply=(
            f"Findings for '{query}' are on screen ({n} hit{'s' if n != 1 else ''}, "
            f"{path.name}), {owner_name()}."
        ),
        skill_id="research",
        metadata={"open_findings": True, "path": str(path), "query": query, "hits": n},
    )


def _open_findings_on_screen(*, prefer_report: bool = False) -> SkillResult:
    """Open research on screen — last web hits by default; report when asked."""
    from friday.persona import owner_name

    order = (
        (_open_latest_report, _open_last_search_html)
        if prefer_report
        else (_open_last_search_html, _open_latest_report)
    )
    for fn in order:
        hit = fn()
        if hit is not None:
            return hit
    return SkillResult(
        reply=(
            f"I don't have search results ready to put on screen, {owner_name()}. "
            "Ask me to research something first."
        ),
        skill_id="research",
        metadata={"open_findings": False},
    )


def _write_findings_html(query: str, hits: list[dict[str, str]]):
    """Write a readable research brief and open it in the default browser."""
    from friday.agent.direct_tools import _html_escape, _write_and_open_html

    items: list[str] = []
    for i, row in enumerate(hits, 1):
        title = _html_escape(row.get("title") or "(untitled)")
        snippet = _html_escape(row.get("snippet") or "")
        url = (row.get("url") or "").strip()
        link = (
            f'<a href="{_html_escape(url)}" target="_blank" rel="noopener">{_html_escape(url)}</a>'
            if url
            else ""
        )
        items.append(
            f"<li><strong>{i}. {title}</strong>"
            + (f"<p>{snippet}</p>" if snippet else "")
            + (f"<div class='url'>{link}</div>" if link else "")
            + "</li>"
        )
    body = "\n".join(items) or "<li>No hits stored.</li>"
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Friday — Research findings</title>
<style>
  :root {{ color-scheme: dark; --bg:#0b1220; --card:#121a2b; --line:#1e2a44;
           --text:#e8eef9; --muted:#8fa3c4; --accent:#3ecbff; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; font-family: "Segoe UI", system-ui, sans-serif; background:
         radial-gradient(1200px 600px at 10% -10%, #1a2744, var(--bg));
         color: var(--text); min-height: 100vh; padding: 2.5rem 1.25rem; }}
  main {{ max-width: 760px; margin: 0 auto; border: 1px solid var(--line);
         background: var(--card); padding: 1.5rem 1.75rem; }}
  h1 {{ margin: 0 0 .35rem; font-weight: 600; letter-spacing: .04em; font-size: 1.35rem; }}
  .eyebrow {{ color: var(--accent); font-size: .72rem; letter-spacing: .16em; text-transform: uppercase; }}
  p.note {{ color: var(--muted); font-size: .85rem; margin: .75rem 0 1.25rem; }}
  ol {{ margin: 0; padding-left: 1.1rem; }}
  li {{ margin: 0 0 1rem; }}
  li p {{ margin: .35rem 0; color: var(--muted); font-size: .92rem; }}
  .url {{ font-size: .8rem; word-break: break-all; }}
  a {{ color: var(--accent); }}
  footer {{ margin-top: 1.25rem; color: var(--muted); font-size: .75rem; }}
</style>
</head>
<body>
<main>
  <div class="eyebrow">Friday · research</div>
  <h1>{_html_escape(query)}</h1>
  <p class="note">Live web hits from this session — open a link to read the source.</p>
  <ol>{body}</ol>
  <footer>Safe to close this tab</footer>
</main>
</body>
</html>
"""
    return _write_and_open_html(html, stem="friday-research")


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
    from friday.prompts import research_doctrine_prompt

    brief = format_results(search_q, rows)
    prompt = research_doctrine_prompt(search_q, brief)
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
        system_overlay=OVERLAY_RESEARCH,
    )

    def run(self, ctx: SkillContext) -> SkillResult:
        msg = ctx.message or ""
        try:
            from friday.assistant.reflexes import _is_greeting_only, try_reflex
            from friday.persona import owner_name

            # "Hey Friday" is a hello — never google paintings named Holy Friday.
            if _is_greeting_only(msg):
                hit = try_reflex(msg)
                if hit:
                    return SkillResult(reply=hit.reply, skill_id="chat", metadata={"greeting_guard": True})
                return SkillResult(
                    reply=f"Here, {owner_name()}. What do you need?",
                    skill_id="chat",
                    metadata={"greeting_guard": True},
                )
        except Exception:  # noqa: BLE001
            pass
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
            return _open_findings_on_screen(prefer_report=True)
        if _SHOW_FINDINGS.search(msg):
            return _open_findings_on_screen(prefer_report=False)

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
