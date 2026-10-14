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
    ARTICLE_ENRICH_DEEP,
    ARTICLE_ENRICH_QUICK,
    DEEP_TIME_BUDGET_S,
    MAX_IMAGES,
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


def _fetch_sources(
    questions: list[str],
    *,
    max_sources: int,
    emit: EmitFn | None,
    mode: str = "quick",
    topic: str = "",
) -> list[dict]:
    from friday.knowledge.enrich import duckduckgo_images, enrich_source_row, wikipedia_brief
    from friday.knowledge.search import fetch_web_results

    seen_urls: set[str] = set()
    sources: list[dict] = []
    images: list[dict] = []

    # Wikipedia brief first — reliable prose + thumbnail for the dossier hero.
    try:
        wiki = wikipedia_brief(topic or (questions[0] if questions else ""))
        if wiki and wiki.get("url") and wiki["url"] not in seen_urls:
            seen_urls.add(wiki["url"])
            sid = f"s{len(sources)+1}"
            src = {
                "id": sid,
                "url": wiki["url"],
                "title": wiki.get("title") or "Wikipedia",
                "domain": "en.wikipedia.org",
                "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "text": (wiki.get("text") or wiki.get("snippet") or "")[:MAX_SOURCE_TEXT],
                "snippet": (wiki.get("snippet") or "")[:500],
                "image": wiki.get("image") or "",
                "kind": "wikipedia",
                "credibility": credibility_for(wiki["url"], wiki.get("title") or ""),
            }
            sources.append(src)
            if src["image"]:
                images.append({"image": src["image"], "url": src["url"], "title": src["title"], "source_id": sid})
            _emit(emit, "source_found", source_id=sid, title=src["title"], domain=src["domain"], url=src["url"])
    except Exception as exc:  # noqa: BLE001
        print(f"[Report] wikipedia skip: {exc}")

    enrich_budget = ARTICLE_ENRICH_DEEP if mode == "deep" else ARTICLE_ENRICH_QUICK
    enriched = 0

    for q in questions:
        if _cancelled() or len(sources) >= max_sources:
            break
        _emit(emit, "query", query=q)
        rows = fetch_web_results(q, limit=min(6, max_sources - len(sources) + 2))
        for row in rows:
            if _cancelled() or len(sources) >= max_sources:
                break
            url = (row.get("url") or "").strip()
            if not url or url in seen_urls:
                continue
            if not url.startswith(("http://", "https://")):
                continue
            seen_urls.add(url)
            do_body = enriched < enrich_budget
            try:
                rich = enrich_source_row(row, fetch_body=do_body)
                if do_body:
                    enriched += 1
            except Exception:  # noqa: BLE001
                rich = {
                    "title": (row.get("title") or url)[:300],
                    "url": url,
                    "snippet": (row.get("snippet") or "")[:2000],
                    "text": f"{row.get('title') or ''}. {row.get('snippet') or ''}".strip(),
                    "image": "",
                    "domain": (urlparse(url).hostname or "").removeprefix("www."),
                    "kind": "web",
                }
            title = (rich.get("title") or url)[:300]
            snippet = (rich.get("snippet") or "")[:2000]
            text = (rich.get("text") or f"{title}. {snippet}").strip()[:MAX_SOURCE_TEXT]
            domain = rich.get("domain") or (urlparse(url).hostname or "").removeprefix("www.")
            sid = f"s{len(sources)+1}"
            src = {
                "id": sid,
                "url": url,
                "title": title,
                "domain": domain,
                "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "text": text,
                "snippet": snippet,
                "image": rich.get("image") or "",
                "kind": rich.get("kind") or "web",
                "credibility": credibility_for(url, title),
            }
            sources.append(src)
            if src["image"] and len(images) < MAX_IMAGES:
                images.append({"image": src["image"], "url": url, "title": title, "source_id": sid})
            _emit(emit, "source_found", source_id=sid, title=title, domain=domain, url=url)
            _emit(emit, "note", source_id=sid, text=f"Q: {q}\nTitle: {title}\nNote: {snippet[:400]}"[:500])

    # Image strip for the dossier (even when pages lack og:image).
    if len(images) < 3 and topic:
        try:
            for im in duckduckgo_images(topic, limit=MAX_IMAGES - len(images)):
                if not im.get("image"):
                    continue
                images.append({**im, "source_id": ""})
                if len(images) >= MAX_IMAGES:
                    break
        except Exception as exc:  # noqa: BLE001
            print(f"[Report] images skip: {exc}")

    # Stash gallery on first source container via side channel — caller attaches to doc.
    _fetch_sources._last_images = images  # type: ignore[attr-defined]
    return sources


def _last_fetch_images() -> list[dict]:
    return list(getattr(_fetch_sources, "_last_images", []) or [])


def _synthesize(query: str, mode: str, sources: list[dict], *, think: bool) -> dict[str, Any]:
    from friday.models.local import query_model_text

    src_block = []
    for s in sources:
        src_block.append(
            f"[{s['id']}] {s['title']} ({s['domain']})\nTEXT:\n{s['text'][:3000]}\n"
        )
    prompt = (
        "You are Friday producing a boss-level research briefing as JSON.\n"
        "Rules:\n"
        "- Write a sharp TL;DR (2–4 sentences) a busy principal can act on.\n"
        "- Include 4–8 findings with clear titles and bodies grounded in SOURCES.\n"
        "- Prefer useful findings over sparse perfect claims. If you include claims, "
        "evidence should be an exact contiguous substring of that source TEXT.\n"
        "- source_id must be one of the listed ids. Do not invent URLs or numbers.\n"
        "- Call out uncertainties and open questions when the sources disagree or are thin.\n"
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


def _dossier_from_sources(query: str, sources: list[dict], reason: str = "") -> dict[str, Any]:
    """Boss-grade brief even when strict claim validation fails — never return an empty baby report."""
    findings = []
    for i, s in enumerate(sources[:12], 1):
        body = (s.get("snippet") or s.get("text") or "")[:700].strip()
        if not body:
            continue
        findings.append(
            {
                "id": f"f{i}",
                "title": (s.get("title") or s.get("domain") or f"Source {i}")[:200],
                "body": body,
                "confidence": 0.55 if s.get("kind") == "wikipedia" else 0.45,
                "source_ids": [s.get("id") or f"s{i}"],
            }
        )
    wiki = next((s for s in sources if s.get("kind") == "wikipedia"), None)
    lead = (wiki.get("text") if wiki else "") or ""
    if not lead and sources:
        lead = (sources[0].get("text") or sources[0].get("snippet") or "")[:500]
    bits = [f"• {(s.get('title') or 'Source')[:80]}" for s in sources[:6]]
    tldr = (
        (lead[:700] + ("…" if len(lead) > 700 else ""))
        if lead
        else f"Briefing pack for “{query}” with {len(sources)} sources."
    )
    if bits:
        tldr = (tldr + "\n\nTop sources:\n" + "\n".join(bits))[:1200]
    return {
        "schema_version": "1",
        "summary": {
            "tldr": tldr,
            "confidence": 0.5 if sources else 0.15,
            "rationale": reason or "Compiled from live web sources (dossier mode).",
        },
        "findings": findings,
        "claims": [],
        "charts": [],
        "uncertainties": [reason] if reason else [],
        "open_questions": [],
        "pros": [],
        "cons": [],
        "next_actions": [],
        "fallback_plain": False,
        "dossier": True,
        "fallback_reason": reason,
    }


def _plain_fallback(query: str, sources: list[dict], reason: str) -> dict[str, Any]:
    return _dossier_from_sources(query, sources, reason=reason)


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
    images: list[dict] = []
    if use_web:
        sources = _fetch_sources(
            questions,
            max_sources=_max_sources(mode),
            emit=emit,
            mode=mode,
            topic=query,
        )
        images = _last_fetch_images()
        _trace("fetch", f"{len(sources)} sources · {len(images)} images")
    else:
        _trace("fetch", "think mode — no web")

    if _cancelled():
        doc = _plain_fallback(query, sources, "cancelled")
        doc.update({
            "id": rid,
            "query": query,
            "mode": mode,
            "created_at": created,
            "sources": sources,
            "images": images,
            "trace": trace,
        })
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
            "images": images,
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

        # If the model returned a weak empty shell, fill findings from live sources.
        if not (draft.get("findings") or draft.get("claims")) and sources:
            filled = _dossier_from_sources(query, sources, reason="model returned empty shell")
            draft["findings"] = filled["findings"]
            draft["summary"] = filled["summary"]
            draft["dossier"] = True

        validated, mech_issues = validate_mechanics(draft)
        issues = mech_issues
        schema_errs = validate_report_schema(validated)
        _emit(emit, "validation", issues=mech_issues[:20], schema_errors=schema_errs[:10], attempt=attempt)
        _trace("validation", f"issues={len(mech_issues)} schema={len(schema_errs)}")
        # Accept claims OR findings — don't discard a usable brief for missing substring claims.
        if not schema_errs and (validated.get("claims") or validated.get("findings")):
            validated["images"] = images
            if save:
                save_report(validated, snapshot={"ui": "v2"})
            _emit(
                emit,
                "final",
                report_id=rid,
                fallback=False,
                claims=len(validated.get("claims") or []),
                findings=len(validated.get("findings") or []),
            )
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
        "images": images,
        "trace": trace,
        "comparison_table": {"headers": [], "rows": []},
        "timeline": [],
        "charts": [],
        "decision_matrix": {},
    })
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
