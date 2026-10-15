"""Fast Quick-mode research: one web search → simple HTML page (+ save a light report).

Deep/think still use the full dossier pipeline. Quick is meant to answer in seconds.
"""

from __future__ import annotations

import html
import os
import tempfile
import time
import uuid
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

EmitFn = Callable[[str, dict], None]


def _emit(emit: EmitFn | None, typ: str, **payload: Any) -> None:
    if emit:
        try:
            emit(typ, payload)
        except TypeError:
            emit(typ, **payload)  # type: ignore[misc]
    try:
        from friday.ui.events import emit as bus_emit

        bus_emit(f"report_{typ}", **payload)
    except Exception:  # noqa: BLE001
        pass


def _domain(url: str) -> str:
    try:
        return urlparse(url).hostname.replace("www.", "") if url else ""
    except Exception:  # noqa: BLE001
        return ""


def _short_tldr(query: str, rows: list[dict[str, str]]) -> str:
    """One-line briefing without a long model wait — prefer snippets, optional tiny model."""
    if not rows:
        return f"No web results came back for “{query}”."
    bits = []
    for r in rows[:4]:
        snip = (r.get("snippet") or r.get("title") or "").strip()
        if snip:
            bits.append(snip[:160])
    if bits:
        return " · ".join(bits)[:500]
    return f"Found {len(rows)} sources on “{query}”."


def _build_html(query: str, rows: list[dict[str, str]], tldr: str, images: list[dict[str, str]]) -> str:
    cards = []
    for i, r in enumerate(rows, 1):
        title = html.escape(r.get("title") or "(untitled)")
        snip = html.escape(r.get("snippet") or "")
        url = r.get("url") or ""
        href = html.escape(url, quote=True)
        dom = html.escape(_domain(url) or "link")
        link = f'<a href="{href}" rel="noopener noreferrer" target="_blank">{dom}</a>' if url else ""
        cards.append(
            f'<article class="card"><h2>{i}. {title}</h2>'
            f'<p class="snip">{snip}</p><p class="src">{link}</p></article>'
        )
    imgs = []
    for im in images[:8]:
        raw = (im.get("image") or im.get("url") or "").strip()
        src = html.escape(raw, quote=True)
        alt = html.escape(im.get("title") or query)
        if raw.startswith("http"):
            imgs.append(f'<figure><img src="{src}" alt="{alt}" loading="lazy" referrerpolicy="no-referrer"/></figure>')
    img_block = f'<div class="gallery">{"".join(imgs)}</div>' if imgs else ""
    q = html.escape(query)
    t = html.escape(tldr)
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Friday · {q}</title>
<style>
:root {{ --bg:#0b121a; --fg:#e8f0f8; --muted:#8aa0b5; --line:#1e2e40; --accent:#3ecbff; }}
* {{ box-sizing: border-box; }}
body {{ margin:0; font:16px/1.5 "Segoe UI", system-ui, sans-serif; background:var(--bg); color:var(--fg); }}
main {{ max-width: 52rem; margin: 0 auto; padding: 1.5rem 1.25rem 3rem; }}
h1 {{ font-size: 1.6rem; letter-spacing: 0.02em; margin: 0 0 0.4rem; }}
.eyebrow {{ font: 0.72rem/1 ui-monospace, monospace; letter-spacing: 0.16em; color: var(--accent); text-transform: uppercase; }}
.tldr {{ color: var(--muted); margin: 0 0 1.4rem; padding-bottom: 1rem; border-bottom: 1px solid var(--line); }}
.card {{ border: 1px solid var(--line); padding: 0.9rem 1rem; margin: 0 0 0.75rem; background: #0e1722; }}
.card h2 {{ font-size: 1.05rem; margin: 0 0 0.35rem; font-weight: 600; }}
.snip {{ margin: 0 0 0.35rem; color: #c5d4e4; }}
.src a {{ color: var(--accent); text-decoration: none; font-size: 0.85rem; }}
.gallery {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 10px; margin: 0 0 1.5rem; }}
.gallery figure {{ margin: 0; }}
.gallery img {{ width: 100%; height: 140px; object-fit: cover; border: 1px solid var(--line); background: #000; display: block; }}
.foot {{ color: var(--muted); font-size: 0.78rem; margin-top: 1.5rem; }}
</style></head><body><main>
<p class="eyebrow">Friday · quick research</p>
<h1>{q}</h1>
<p class="tldr">{t}</p>
{img_block}
{"".join(cards) or "<p class='tldr'>No sources.</p>"}
<p class="foot">Pulled from web search · opened locally · Deep mode still available for a full dossier.</p>
</main></body></html>"""


def _open_html(html_text: str, stem: str = "friday-quick") -> Path:
    root = Path(tempfile.gettempdir()) / "friday-reports"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{stem}-{uuid.uuid4().hex[:8]}.html"
    path.write_text(html_text, encoding="utf-8")
    try:
        webbrowser.open(path.as_uri())
    except Exception:  # noqa: BLE001
        os.startfile(str(path))  # type: ignore[attr-defined]
    return path


def run_quick_html_report(
    query: str,
    *,
    emit: EmitFn | None = None,
    save: bool = True,
    open_browser: bool = True,
) -> dict[str, Any]:
    """Search once, open a simple HTML brief, save a light report for the canvas."""
    from friday.knowledge.search import fetch_web_results
    from friday.reports.store import save_report

    q = (query or "").strip()
    rid = uuid.uuid4().hex[:12]
    created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    _emit(emit, "plan", query=q, mode="quick")
    _emit(emit, "query", query=q)

    t0 = time.monotonic()
    rows = fetch_web_results(q, limit=8)
    images: list[dict[str, str]] = []
    wiki_snip = ""
    wiki = None
    try:
        from friday.knowledge.enrich import collect_topic_images, wikipedia_brief

        wiki = wikipedia_brief(q)
        if wiki:
            wiki_snip = (wiki.get("snippet") or wiki.get("text") or "")[:400]
            if wiki.get("url") and not any((r.get("url") or "") == wiki["url"] for r in rows):
                rows = [
                    {
                        "title": wiki.get("title") or q,
                        "url": wiki["url"],
                        "snippet": wiki_snip or (wiki.get("snippet") or ""),
                    },
                    *rows,
                ][:8]
        images = collect_topic_images(q, limit=6, wiki=wiki) or []
    except Exception as exc:  # noqa: BLE001
        _emit(emit, "note", text=f"Images skipped: {exc}")
        images = []

    sources: list[dict[str, Any]] = []
    for i, r in enumerate(rows):
        url = r.get("url") or ""
        sid = f"s{i + 1}"
        sources.append({
            "id": sid,
            "title": (r.get("title") or "")[:200],
            "url": url[:500],
            "domain": _domain(url),
            "snippet": (r.get("snippet") or "")[:400],
            "fetched_at": created,
            "credibility": 0.65 if wiki and url == (wiki.get("url") or "") else 0.5,
        })
        _emit(emit, "source_found", source_id=sid, title=sources[-1]["title"], domain=sources[-1]["domain"], url=url)

    tldr = wiki_snip or _short_tldr(q, rows)
    if images:
        _emit(emit, "note", text=f"{len(images)} image(s) for gallery")
    findings = [
        {
            "id": f"f{i + 1}",
            "title": (r.get("title") or "Result")[:160],
            "body": (r.get("snippet") or "")[:500],
            "confidence": 0.55,
            "source_ids": [f"s{i + 1}"],
        }
        for i, r in enumerate(rows[:8])
    ]
    claims = [
        {
            "id": f"c{i + 1}",
            "claim": (r.get("title") or "")[:200],
            "source_id": f"s{i + 1}",
            "evidence": (r.get("snippet") or "")[:300],
        }
        for i, r in enumerate(rows[:6])
        if r.get("title")
    ]

    html_path = None
    if open_browser:
        try:
            html_path = _open_html(_build_html(q, rows, tldr, images), stem="friday-quick")
            _emit(emit, "note", text=f"Opened HTML brief: {html_path.name}")
        except Exception as exc:  # noqa: BLE001
            _emit(emit, "note", text=f"HTML open failed: {exc}")

    doc: dict[str, Any] = {
        "schema_version": "1",
        "id": rid,
        "query": q,
        "mode": "quick",
        "created_at": created,
        "sources": sources,
        "images": images,
        "findings": findings,
        "claims": claims,
        "charts": [],
        "comparison_table": {"headers": [], "rows": []},
        "timeline": [],
        "uncertainties": [] if rows else ["No web results returned."],
        "open_questions": [],
        "pros": [],
        "cons": [],
        "decision_matrix": {},
        "next_actions": [],
        "summary": {
            "tldr": tldr,
            "confidence": 0.55 if rows else 0.1,
            "rationale": f"quick html brief · {len(rows)} sources · {time.monotonic() - t0:.1f}s",
        },
        "trace": [{"step": "quick_html", "detail": f"{len(rows)} hits", "query": q}],
        "fallback_plain": not bool(rows),
        "html_path": str(html_path) if html_path else "",
        "dossier": False,
    }
    if save:
        save_report(doc, snapshot={"ui": "quick_html"})
    _emit(
        emit,
        "final",
        report_id=rid,
        fallback=not bool(rows),
        claims=len(claims),
        findings=len(findings),
        html_opened=bool(html_path),
    )
    _emit(emit, "section_ready", section="report", report_id=rid)
    return doc
