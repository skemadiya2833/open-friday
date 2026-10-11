"""Research report pipeline: plan → search → notes → synthesize → validate."""

from __future__ import annotations

import json
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlparse

from friday.reports.credibility import credibility_for
from friday.reports.limits import (
    DEEP_TIME_BUDGET_S,
    MAX_SOURCE_TEXT,
    MAX_SOURCES_DEEP,
    MAX_SOURCES_QUICK,
    SYNTHESIS_TIMEOUT_S,
)
from friday.reports.schema_load import validate_report_schema
from friday.reports.store import save_report
from friday.reports.validate import validate_mechanics

EmitFn = Callable[[str, dict], None]

PLAN_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "sub_questions": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 6,
        }
    },
    "required": ["sub_questions"],
}

REPORT_OUT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "summary": {
            "type": "object",
            "properties": {
                "tldr": {"type": "string"},
                "confidence": {"type": "number"},
                "rationale": {"type": "string"},
            },
            "required": ["tldr", "confidence", "rationale"],
        },
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                    "confidence": {"type": "number"},
                    "source_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["id", "title", "body", "confidence"],
            },
        },
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "claim": {"type": "string"},
                    "source_id": {"type": "string"},
                    "evidence": {"type": "string"},
                },
                "required": ["id", "claim", "source_id", "evidence"],
            },
        },
        "uncertainties": {"type": "array", "items": {"type": "string"}},
        "open_questions": {"type": "array", "items": {"type": "string"}},
        "pros": {"type": "array", "items": {"type": "string"}},
        "cons": {"type": "array", "items": {"type": "string"}},
        "comparison_table": {
            "type": "object",
            "properties": {
                "headers": {"type": "array", "items": {"type": "string"}},
                "rows": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}},
            },
        },
        "timeline": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "when": {"type": "string"},
                    "event": {"type": "string"},
                    "source_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["when", "event"],
            },
        },
        "charts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "kind": {"type": "string"},
                    "series": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "label": {"type": "string"},
                                "value": {"type": "number"},
                                "source_id": {"type": "string"},
                                "snippet": {"type": "string"},
                            },
                            "required": ["label", "value", "source_id", "snippet"],
                        },
                    },
                },
                "required": ["id", "title", "kind", "series"],
            },
        },
        "decision_matrix": {"type": "object"},
        "next_actions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "tool": {"type": "string"},
                    "args": {"type": "object"},
                    "note": {"type": "string"},
                },
                "required": ["label", "tool"],
            },
        },
    },
    "required": ["summary", "claims"],
}


def _emit(emit: EmitFn | None, typ: str, **payload: Any) -> None:
    if emit:
        try:
            emit(typ, payload)
        except TypeError:
            emit(typ, **payload)  # type: ignore[misc]
    try:
        from friday.ui.events import emit as bus_emit

        bus_emit(f"report_{typ}", **payload)
    except Exception:
        pass


def _cancelled() -> bool:
    try:
        from friday.agent.control import get_controller

        ctrl = get_controller()
        return bool(ctrl and ctrl.should_stop())
    except Exception:
        return False


def _max_sources(mode: str) -> int:
    if mode == "quick":
        return MAX_SOURCES_QUICK
    if mode == "deep":
        return MAX_SOURCES_DEEP
    return 0


def _plan_questions(query: str, mode: str) -> list[str]:
    if mode == "think":
        return [query]
    from friday.models.local import query_model_text

    prompt = (
        f"Break this research topic into 2-4 focused web search sub-questions.\n"
        f"Topic: {query}\nReturn JSON only."
    )
    out = query_model_text(
        prompt,
        format_schema=PLAN_SCHEMA,
        think=False,
        num_predict=256,
        num_ctx=2048,
    )
    raw = out.get("message") or out.get("raw") or ""
    qs: list = []
    if isinstance(out, dict) and isinstance(out.get("sub_questions"), list):
        qs = out["sub_questions"]
    else:
        try:
            parsed = json.loads(raw)
            qs = parsed.get("sub_questions") or []
        except Exception:
            # tolerate ```json fences
            m = re.search(r"\{[\s\S]*\}", raw)
            if m:
                try:
                    qs = json.loads(m.group(0)).get("sub_questions") or []
                except Exception:
                    qs = [query]
            else:
                qs = [query]
    qs = [str(q).strip() for q in qs if str(q).strip()][:4]
    return qs or [query]


def _fetch_sources(questions: list[str], *, max_sources: int, emit: EmitFn | None) -> list[dict]:
    from friday.knowledge.search import fetch_web_results

    seen_urls: set[str] = set()
    sources: list[dict] = []
    for q in questions:
        if _cancelled() or len(sources) >= max_sources:
            break
        _emit(emit, "query", query=q)
        rows = fetch_web_results(q, limit=min(4, max_sources - len(sources) + 1))
        for row in rows:
            if _cancelled() or len(sources) >= max_sources:
                break
            url = (row.get("url") or "").strip()
            if not url or url in seen_urls:
                continue
            if not url.startswith(("http://", "https://")):
                continue
            seen_urls.add(url)
            title = (row.get("title") or url)[:300]
            snippet = (row.get("snippet") or "")[:2000]
            text = f"{title}. {snippet}".strip()[:MAX_SOURCE_TEXT]
            domain = (urlparse(url).hostname or "").removeprefix("www.")
            sid = f"s{len(sources)+1}"
            src = {
                "id": sid,
                "url": url,
                "title": title,
                "domain": domain,
                "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "text": text,
                "credibility": credibility_for(url, title),
            }
            sources.append(src)
            _emit(emit, "source_found", source_id=sid, title=title, domain=domain, url=url)
            note = f"Q: {q}\nTitle: {title}\nNote: {snippet[:400]}"
            _emit(emit, "note", source_id=sid, text=note[:500])
    return sources


def _synthesize(query: str, mode: str, sources: list[dict], *, think: bool) -> dict[str, Any]:
    from friday.models.local import query_model_text

    src_block = []
    for s in sources:
        src_block.append(
            f"[{s['id']}] {s['title']} ({s['domain']})\nTEXT:\n{s['text'][:3000]}\n"
        )
    prompt = (
        "You are producing a structured research report JSON.\n"
        "Rules:\n"
        "- Every claim MUST include evidence that is an EXACT contiguous substring of that source TEXT.\n"
        "- Copy evidence verbatim from TEXT (whitespace may differ slightly but words must match).\n"
        "- source_id must be one of the listed ids.\n"
        "- Do not invent URLs or numbers not present in TEXT.\n"
        "- For charts, each value must appear as digits inside its snippet, and snippet must be from TEXT.\n"
        f"Mode: {mode}. Topic: {query}\n\nSOURCES:\n" + "\n".join(src_block)
    )
    t0 = time.monotonic()
    out = query_model_text(
        prompt,
        format_schema=REPORT_OUT_SCHEMA,
        think=bool(think),
        num_predict=1800,
        num_ctx=8192,
    )
    if time.monotonic() - t0 > SYNTHESIS_TIMEOUT_S:
        raise TimeoutError("synthesis timeout")
    if out.get("routing") == "FALLBACK_TO_CLOUD":
        raise RuntimeError(out.get("reason") or "model failed")
    if "summary" in out and "claims" in out:
        return out
    raw = out.get("message") or out.get("raw") or "{}"
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", raw)
        if not m:
            raise RuntimeError("bad JSON: no object") from None
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"bad JSON: {exc}") from exc


def _plain_fallback(query: str, sources: list[dict], reason: str) -> dict[str, Any]:
    bits = []
    for s in sources[:4]:
        bits.append(f"{s['title']}: {(s.get('text') or '')[:180]}")
    tldr = (
        f"I could not finish a fully validated structured report ({reason}). "
        f"Here is a plain summary of what came back for “{query}”: "
        + (" ".join(bits) if bits else "no sources.")
    )[:1200]
    return {
        "schema_version": "1",
        "summary": {
            "tldr": tldr,
            "confidence": 0.2,
            "rationale": "Validation failed; plain-text fallback.",
        },
        "findings": [],
        "claims": [],
        "charts": [],
        "uncertainties": [reason],
        "open_questions": [],
        "pros": [],
        "cons": [],
        "next_actions": [],
        "fallback_plain": True,
        "fallback_reason": reason,
    }


def run_research_report(
    query: str,
    *,
    mode: str = "quick",
    emit: EmitFn | None = None,
    allow_web: bool | None = None,
    save: bool = True,
) -> dict[str, Any]:
    """Run the full pipeline. ``mode``: quick | deep | think."""
    mode = mode if mode in ("quick", "deep", "think") else "quick"
    use_web = (mode != "think") if allow_web is None else bool(allow_web)
    rid = uuid.uuid4().hex[:12]
    created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    trace: list[dict] = []
    t_deadline = time.monotonic() + (DEEP_TIME_BUDGET_S if mode == "deep" else 120)

    def _trace(step: str, detail: str, q: str = "") -> None:
        trace.append({"step": step, "detail": detail[:500], "query": q[:400]})

    _emit(emit, "plan", query=query, mode=mode)
    _trace("plan", f"mode={mode}")

    questions = _plan_questions(query, mode)
    _trace("sub_questions", "; ".join(questions))
    _emit(emit, "plan", sub_questions=questions)

    sources: list[dict] = []
    if use_web:
        sources = _fetch_sources(questions, max_sources=_max_sources(mode), emit=emit)
        _trace("fetch", f"{len(sources)} sources")
    else:
        _trace("fetch", "think mode — no web")

    if _cancelled():
        doc = _plain_fallback(query, sources, "cancelled")
        doc.update({"id": rid, "query": query, "mode": mode, "created_at": created, "sources": sources, "trace": trace})
        if save:
            save_report(doc)
        _emit(emit, "final", report_id=rid, cancelled=True)
        return doc

    think_synth = mode in ("deep", "think")
    partial: dict[str, Any] | None = None
    issues: list[str] = []
    for attempt in (1, 2):
        if _cancelled() or time.monotonic() > t_deadline:
            break
        try:
            _emit(emit, "section_ready", section="synthesis", attempt=attempt)
            partial = _synthesize(query, mode, sources, think=think_synth and attempt == 1)
            _trace("synthesize", f"attempt {attempt}")
        except Exception as exc:
            issues.append(str(exc)[:200])
            _trace("synthesize_error", str(exc)[:200])
            continue
        draft = {
            "schema_version": "1",
            "id": rid,
            "query": query,
            "mode": mode,
            "created_at": created,
            "sources": sources,
            "trace": list(trace),
            "findings": partial.get("findings") or [],
            "claims": partial.get("claims") or [],
            "charts": partial.get("charts") or [],
            "comparison_table": partial.get("comparison_table") or {"headers": [], "rows": []},
            "timeline": partial.get("timeline") or [],
            "uncertainties": partial.get("uncertainties") or [],
            "open_questions": partial.get("open_questions") or [],
            "pros": partial.get("pros") or [],
            "cons": partial.get("cons") or [],
            "decision_matrix": partial.get("decision_matrix") if mode == "think" else {},
            "next_actions": partial.get("next_actions") or [],
            "summary": partial.get("summary") or {
                "tldr": "No summary.",
                "confidence": 0.0,
                "rationale": "missing",
            },
            "fallback_plain": False,
        }
        # Sanitize next_actions — suggestions only; execution goes through normal tools
        safe_actions = []
        for a in draft["next_actions"][:8]:
            safe_actions.append({
                "label": str(a.get("label") or "")[:200],
                "tool": str(a.get("tool") or "web_search")[:80],
                "args": a.get("args") if isinstance(a.get("args"), dict) else {},
                "note": "Routed through Friday tools/approvals when the owner runs it.",
            })
        draft["next_actions"] = safe_actions

        validated, mech_issues = validate_mechanics(draft)
        issues = mech_issues
        schema_errs = validate_report_schema(validated)
        _emit(emit, "validation", issues=mech_issues[:20], schema_errors=schema_errs[:10], attempt=attempt)
        _trace("validation", f"issues={len(mech_issues)} schema={len(schema_errs)}")
        if not schema_errs and validated.get("claims"):
            if save:
                save_report(validated, snapshot={"ui": "v1"})
            _emit(emit, "final", report_id=rid, fallback=False, claims=len(validated["claims"]))
            _emit(emit, "section_ready", section="report", report_id=rid)
            return validated
        # retry once with stronger instruction
        if attempt == 1 and sources:
            continue
        break

    reason = "; ".join(issues[:3]) or "validation failed"
    doc = _plain_fallback(query, sources, reason)
    doc.update({
        "id": rid,
        "query": query,
        "mode": mode,
        "created_at": created,
        "sources": sources,
        "trace": trace,
        "comparison_table": {"headers": [], "rows": []},
        "timeline": [],
        "charts": [],
        "decision_matrix": {},
    })
    # schema-ok fallback
    if save:
        save_report(doc)
    _emit(emit, "final", report_id=rid, fallback=True, reason=reason)
    return doc


def dig_deeper(report_id: str, finding_id: str, *, emit: EmitFn | None = None) -> dict[str, Any]:
    """Bounded sub-research on one finding; merge into a new report revision."""
    from friday.reports.store import get_report

    base = get_report(report_id)
    if not base:
        raise ValueError("report not found")
    finding = next((f for f in (base.get("findings") or []) if f.get("id") == finding_id), None)
    topic = (finding or {}).get("title") or finding_id
    sub = run_research_report(
        f"{base.get('query')}: dig deeper — {topic}",
        mode="quick",
        emit=emit,
        save=True,
    )
    return sub
