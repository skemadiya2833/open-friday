"""Enrich search hits with article text, Open Graph images, and Wikipedia briefs.

Used by the research report pipeline so the HUD can show a real dossier —
not just four thin DuckDuckGo snippets.
"""

from __future__ import annotations

import html as htmlmod
import re
import urllib.parse
from typing import Any
from urllib.parse import urlparse

_TAG = re.compile(r"<[^>]+>", re.I)
_WS = re.compile(r"\s+")
_SCRIPT = re.compile(r"<script[\s\S]*?</script>", re.I)
_STYLE = re.compile(r"<style[\s\S]*?</style>", re.I)
_META = re.compile(
    r"""<meta\s+[^>]*(?:property|name)\s*=\s*["']([^"']+)["'][^>]*content\s*=\s*["']([^"']*)["'][^>]*>"""
    r"|"
    r"""<meta\s+[^>]*content\s*=\s*["']([^"']*)["'][^>]*(?:property|name)\s*=\s*["']([^"']+)["'][^>]*>""",
    re.I,
)
_OG_IMG = re.compile(
    r"""<meta[^>]+(?:property|name)=["']og:image["'][^>]+content=["']([^"']+)["']"""
    r"|"
    r"""<meta[^>]+content=["']([^"']+)["'][^>]+(?:property|name)=["']og:image["']""",
    re.I,
)
_TITLE = re.compile(r"<title[^>]*>([\s\S]*?)</title>", re.I)
_P = re.compile(r"<p[^>]*>([\s\S]*?)</p>", re.I)


def _strip(text: str) -> str:
    return _WS.sub(" ", htmlmod.unescape(_TAG.sub(" ", text or ""))).strip()


def _safe_http(url: str) -> str | None:
    u = (url or "").strip()
    if not u.startswith(("http://", "https://")):
        return None
    try:
        from friday.security.ssrf import assert_url_safe

        assert_url_safe(u, resolve=True)
    except Exception:  # noqa: BLE001
        return None
    return u


def _get(url: str, timeout: float = 10.0) -> str:
    import httpx

    from friday.security.ssrf import assert_url_safe

    assert_url_safe(url, resolve=True)
    # Wikimedia rejects generic browser UAs on api.php; identify the app.
    headers = {
        "User-Agent": "OpenFriday/1.0 (local research assistant; https://localhost)",
        "Api-User-Agent": "OpenFriday/1.0 (local research assistant; https://localhost)",
        "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
        r = client.get(url)
        assert_url_safe(str(r.url), resolve=True)
        r.raise_for_status()
        return r.text


def _wiki_summary_doc(title: str) -> dict[str, Any] | None:
    import json

    summary_url = "https://en.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote(
        title.replace(" ", "_"), safe=""
    )
    doc = json.loads(_get(summary_url, timeout=8.0))
    if not isinstance(doc, dict) or doc.get("type") == "https://mediawiki.org/wiki/HyperSwitch/errors/not_found":
        return None
    return doc


def wikipedia_brief(query: str) -> dict[str, Any] | None:
    """Resolve a topic → Wikipedia extract + thumbnail (REST, no fragile scraping)."""
    q = (query or "").strip()
    if len(q) < 2:
        return None
    try:
        import json

        title = q
        # Prefer title search over action=opensearch (often 403 with scrapers).
        try:
            sraw = _get(
                "https://en.wikipedia.org/w/rest.php/v1/search/title?q="
                + urllib.parse.quote_plus(q)
                + "&limit=1",
                timeout=8.0,
            )
            hits = (json.loads(sraw).get("pages") or []) if sraw else []
            if hits and isinstance(hits[0], dict) and hits[0].get("title"):
                title = str(hits[0]["title"])
        except Exception:  # noqa: BLE001
            title = q

        doc = _wiki_summary_doc(title) or _wiki_summary_doc(q.title())
        if not doc:
            return None
        extract = _strip(str(doc.get("extract") or ""))[:4000]
        if not extract:
            return None
        thumb = ""
        t = doc.get("thumbnail") or {}
        if isinstance(t, dict):
            thumb = str(t.get("source") or "")
        # Prefer original/larger when present
        orig = doc.get("originalimage") or {}
        if isinstance(orig, dict) and orig.get("source"):
            thumb = str(orig.get("source") or thumb)
        page_title = str(doc.get("title") or title)
        page_url = str((doc.get("content_urls") or {}).get("desktop", {}).get("page") or "")
        if not page_url:
            page_url = f"https://en.wikipedia.org/wiki/{urllib.parse.quote(page_title.replace(' ', '_'))}"
        return {
            "title": page_title,
            "url": page_url,
            "snippet": extract[:400],
            "text": extract,
            "image": _safe_http(thumb) or "",
            "domain": "en.wikipedia.org",
            "kind": "wikipedia",
        }
    except Exception as exc:  # noqa: BLE001
        print(f"[Enrich] wikipedia failed: {exc}")
        return None


def wikimedia_images(query: str, *, limit: int = 6) -> list[dict[str, str]]:
    """Image hits from Wikimedia Commons search (stable, no bot challenge)."""
    q = (query or "").strip()
    if len(q) < 2 or limit <= 0:
        return []
    try:
        import json

        raw = _get(
            "https://commons.wikimedia.org/w/api.php?"
            + urllib.parse.urlencode(
                {
                    "action": "query",
                    "format": "json",
                    "generator": "search",
                    "gsrsearch": q,
                    "gsrlimit": max(limit, 3),
                    "gsrnamespace": 6,
                    "prop": "imageinfo",
                    "iiprop": "url",
                    "iiurlwidth": 640,
                }
            ),
            timeout=10.0,
        )
        pages = (json.loads(raw).get("query") or {}).get("pages") or {}
        if not isinstance(pages, dict):
            return []
        out: list[dict[str, str]] = []
        for page in pages.values():
            if not isinstance(page, dict):
                continue
            info = (page.get("imageinfo") or [{}])[0]
            if not isinstance(info, dict):
                continue
            img = _safe_http(str(info.get("thumburl") or info.get("url") or ""))
            if not img:
                continue
            title = _strip(str(page.get("title") or "").removeprefix("File:"))[:200]
            page_url = _safe_http(str(info.get("descriptionurl") or info.get("url") or "")) or img
            out.append({"image": img, "url": page_url, "title": title or "Image"})
            if len(out) >= limit:
                break
        return out
    except Exception as exc:  # noqa: BLE001
        print(f"[Enrich] commons images failed: {exc}")
        return []


def collect_topic_images(
    query: str,
    *,
    limit: int = 6,
    wiki: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """Best-effort gallery: Wikipedia thumb → Commons → DuckDuckGo (often empty)."""
    out: list[dict[str, str]] = []
    seen: set[str] = set()

    def _add(rows: list[dict[str, str]]) -> None:
        for row in rows:
            src = (row.get("image") or row.get("url") or "").strip()
            if not src.startswith("http") or src in seen:
                continue
            seen.add(src)
            out.append(
                {
                    "image": row.get("image") or src,
                    "url": row.get("url") or src,
                    "title": (row.get("title") or "Image")[:200],
                }
            )
            if len(out) >= limit:
                return

    brief = wiki if wiki is not None else wikipedia_brief(query)
    if brief and brief.get("image"):
        _add(
            [
                {
                    "image": brief["image"],
                    "url": brief.get("url") or brief["image"],
                    "title": brief.get("title") or query,
                }
            ]
        )
    if len(out) < limit:
        _add(wikimedia_images(query, limit=limit - len(out)))
    if len(out) < limit:
        _add(duckduckgo_images(query, limit=limit - len(out)))
    return out[:limit]


def fetch_article(url: str, *, max_chars: int = 6000) -> dict[str, Any]:
    """Pull title, description, og:image, and readable paragraph text from a URL."""
    out: dict[str, Any] = {
        "url": url,
        "title": "",
        "text": "",
        "image": "",
        "description": "",
    }
    safe = _safe_http(url)
    if not safe:
        return out
    try:
        raw = _get(safe, timeout=12.0)
    except Exception as exc:  # noqa: BLE001
        print(f"[Enrich] article fetch failed {safe[:60]}: {exc}")
        return out

    cleaned = _SCRIPT.sub(" ", raw)
    cleaned = _STYLE.sub(" ", cleaned)
    tm = _TITLE.search(cleaned)
    if tm:
        out["title"] = _strip(tm.group(1))[:300]

    meta: dict[str, str] = {}
    for m in _META.finditer(cleaned):
        if m.group(1) and m.group(2) is not None:
            meta[m.group(1).lower()] = htmlmod.unescape(m.group(2))
        elif m.group(4) and m.group(3) is not None:
            meta[m.group(4).lower()] = htmlmod.unescape(m.group(3))
    out["description"] = _strip(
        meta.get("og:description") or meta.get("description") or meta.get("twitter:description") or ""
    )[:800]
    if not out["title"]:
        out["title"] = _strip(meta.get("og:title") or "")[:300]

    im = _OG_IMG.search(cleaned)
    if im:
        out["image"] = _safe_http(im.group(1) or im.group(2) or "") or ""
    if not out["image"]:
        img = meta.get("og:image") or meta.get("twitter:image") or ""
        out["image"] = _safe_http(img) or ""

    paras: list[str] = []
    for pm in _P.finditer(cleaned):
        t = _strip(pm.group(1))
        if len(t) < 40:
            continue
        paras.append(t)
        if sum(len(p) for p in paras) >= max_chars:
            break
    body = " ".join(paras)[:max_chars]
    if not body and out["description"]:
        body = out["description"]
    out["text"] = body
    return out


def duckduckgo_images(query: str, *, limit: int = 6) -> list[dict[str, str]]:
    """Best-effort image hits via DDG image JSON endpoint (no API key)."""
    q = (query or "").strip()
    if len(q) < 2:
        return []
    try:
        # vqd bootstrap page, then i.js — fragile but free; fail soft.
        boot = _get(
            "https://duckduckgo.com/?q=" + urllib.parse.quote_plus(q) + "&iax=images&ia=images",
            timeout=8.0,
        )
        m = re.search(r"vqd=['\"]([^'\"]+)['\"]", boot)
        if not m:
            return []
        vqd = m.group(1)
        api = (
            "https://duckduckgo.com/i.js?l=us-en&o=json&q="
            + urllib.parse.quote_plus(q)
            + "&vqd="
            + urllib.parse.quote_plus(vqd)
            + "&f=,,,&p=1"
        )
        import json

        raw = _get(api, timeout=10.0)
        data = json.loads(raw)
        rows = data.get("results") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            return []
        out: list[dict[str, str]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            img = _safe_http(str(row.get("image") or row.get("thumbnail") or ""))
            page = _safe_http(str(row.get("url") or row.get("source") or ""))
            title = _strip(str(row.get("title") or ""))[:200]
            if not img:
                continue
            out.append({"image": img, "url": page or img, "title": title or "Image"})
            if len(out) >= limit:
                break
        return out
    except Exception as exc:  # noqa: BLE001
        print(f"[Enrich] ddg images failed: {exc}")
        return []


def enrich_source_row(row: dict[str, str], *, fetch_body: bool = True) -> dict[str, Any]:
    """Merge search snippet with live page extract when possible."""
    url = (row.get("url") or "").strip()
    base = {
        "title": (row.get("title") or "")[:300],
        "url": url,
        "snippet": (row.get("snippet") or "")[:2000],
        "text": "",
        "image": "",
        "domain": (urlparse(url).hostname or "").removeprefix("www."),
        "kind": "web",
    }
    if fetch_body and url.startswith("http"):
        art = fetch_article(url)
        if art.get("title") and len(art["title"]) > 3:
            base["title"] = art["title"]
        text = (art.get("text") or art.get("description") or "").strip()
        if text:
            base["text"] = text
        if art.get("image"):
            base["image"] = art["image"]
        if art.get("description") and not base["snippet"]:
            base["snippet"] = art["description"][:500]
    if not base["text"]:
        base["text"] = f"{base['title']}. {base['snippet']}".strip()
    return base
