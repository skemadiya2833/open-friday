"""Look something up and return readable results — do not spam browser tabs."""

from __future__ import annotations

import html as htmlmod
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

from friday.types import KnowledgeNote

_CACHE_TTL = 10 * 60
# (timestamp, note, raw rows) — rows kept so we can open findings on screen later.
_cache: dict[str, tuple[float, KnowledgeNote, list[dict[str, str]]]] = {}
_last_key: str | None = None
_NEWS = re.compile(
    r"\b(news|headline|headlines|breaking|current events|today'?s news)\b",
    re.I,
)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def reset_cache() -> None:
    global _last_key
    _cache.clear()
    _last_key = None


def last_search_payload() -> tuple[str, list[dict[str, str]], str] | None:
    """Most recent web search: (query, rows, summary). None if nothing cached."""
    if not _last_key:
        return None
    hit = _cache.get(_last_key)
    if not hit:
        return None
    _ts, note, rows = hit
    return note.query, list(rows), note.summary


def _norm(query: str) -> str:
    return _WS.sub(" ", query.strip().lower())


def _strip(text: str) -> str:
    return _WS.sub(" ", htmlmod.unescape(_TAG.sub(" ", text or ""))).strip()


def clean_web_query(raw: str) -> str:
    """Strip assistant scaffolding so we search 'latest songs', not 'Can you search about…'."""
    from datetime import datetime

    t = _WS.sub(" ", (raw or "").strip())
    if not t:
        return ""
    t = re.sub(
        r"(?i)\b("
        r"please|hey|hi|okay|ok|friday|boss|"
        r"can you|could you|would you|will you|"
        r"do (?:a |me a )?(?:little |quick |small |fast )?(?:web |google |online )?(?:search|lookup|research)|"
        r"search\s+up|search(?:es|ing)?(?: the web| google| online| for me)?|"
        r"look(?:ing)?\s*ups?|pull(?:ing)?\s+up|research(?:ing|es)?|google|find out|"
        r"for me|real quick|quickly|something|stuff|things?|a bit|a little|"
        r"the web|online|internet|about|regarding|concerning"
        r")\b",
        " ",
        t,
    )
    t = re.sub(r"(?i)^\s*(for|on|of|to|up|the)\s+", "", t)
    t = re.sub(r"(?i)^\s*up\s+", "", t)
    t = _WS.sub(" ", t).strip(" .?!,;:\"'")
    if len(t) < 2:
        return (raw or "").strip()[:200]
    # Time-sensitive music / news asks need a year or they return “how to discover” fluff.
    year = str(datetime.now().year)
    if re.search(r"(?i)\b(latest|new|new(?:est)?|current|trending|top)\b.{0,40}\b(songs?|tracks?|singles?|hits?|music)\b", t):
        if year not in t:
            t = f"{t} {year} new releases"
    elif re.search(r"(?i)\b(latest|breaking|today'?s?)\b.{0,30}\b(news|headlines)\b", t):
        if year not in t and "today" not in t.lower():
            t = f"{t} {year}"
    return t[:200]


class _DDGParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.results: list[dict[str, str]] = []
        self._href = ""
        self._buf: list[str] = []
        self._kind = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        cls = dict(attrs).get("class") or ""
        href = dict(attrs).get("href") or ""
        if tag == "a" and "result__a" in cls:
            self._kind, self._href, self._buf = "title", href, []
        elif "result__snippet" in cls:
            self._kind, self._buf = "snip", []

    def handle_data(self, data: str) -> None:
        if self._kind:
            self._buf.append(data)

    def handle_endtag(self, tag: str) -> None:
        if not self._kind:
            return
        if self._kind == "title" and tag == "a":
            title = _strip("".join(self._buf))
            url = _ddg_url(self._href)
            if title:
                self.results.append({"title": title, "url": url, "snippet": ""})
            self._kind = ""
        elif self._kind == "snip" and tag in ("a", "td", "span", "div"):
            snip = _strip("".join(self._buf))
            if snip and self.results and not self.results[-1].get("snippet"):
                self.results[-1]["snippet"] = snip
            self._kind = ""


def _ddg_url(href: str) -> str:
    if "uddg=" in href:
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
        if qs.get("uddg"):
            return urllib.parse.unquote(qs["uddg"][0])
    if href.startswith("//"):
        return "https:" + href
    return href


def _get(url: str, timeout: float = 12.0) -> str:
    import httpx

    from friday.security.ssrf import assert_url_safe

    assert_url_safe(url, resolve=True)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Friday) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
        r = client.get(url)
        # Re-check final URL after redirects (SSRF via open redirect).
        assert_url_safe(str(r.url), resolve=True)
        r.raise_for_status()
        return r.text


def _duckduckgo(query: str, limit: int) -> list[dict[str, str]]:
    raw = _get("https://html.duckduckgo.com/html/?q=" + urllib.parse.quote_plus(query))
    p = _DDGParser()
    p.feed(raw)
    return p.results[:limit]


def _news_rss(query: str, limit: int) -> list[dict[str, str]]:
    q = urllib.parse.quote_plus(query)
    raw = _get(f"https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en")
    root = ET.fromstring(raw)
    out: list[dict[str, str]] = []
    for item in root.iter("item"):
        title = _strip(item.findtext("title") or "")
        link = (item.findtext("link") or "").strip()
        src = _strip(item.findtext("source") or "")
        if not title:
            continue
        out.append({"title": title, "url": link, "snippet": src})
        if len(out) >= limit:
            break
    return out


def fetch_web_results(query: str, *, limit: int = 8) -> list[dict[str, str]]:
    """Network fetch (DuckDuckGo + News). Tests patch this. Never opens a browser."""
    found: list[dict[str, str]] = []
    errors: list[str] = []
    # Always pull news + web for a thicker brief (news used to be news-query only).
    try:
        found.extend(_news_rss(query, max(3, limit // 2)))
    except Exception as exc:  # noqa: BLE001
        errors.append(f"news:{type(exc).__name__}")
    try:
        found.extend(_duckduckgo(query, limit))
    except Exception as exc:  # noqa: BLE001
        errors.append(f"ddg:{type(exc).__name__}")
    if _NEWS.search(query) or _norm(query) in {"news", "today", "headlines"}:
        try:
            found.extend(_news_rss(query + " latest", limit))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"news2:{type(exc).__name__}")
    seen: set[str] = set()
    uniq: list[dict[str, str]] = []
    for row in found:
        key = _norm(row.get("url") or "") or _norm(row.get("title") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        uniq.append(row)
        if len(uniq) >= limit:
            break
    if errors and not uniq:
        print(f"[Knowledge] fetch failed for {query!r}: {errors}", flush=True)
    return uniq


def format_results(query: str, rows: list[dict[str, str]]) -> str:
    from friday.security.content_scan import apply_injection
    from friday.security.taint import fence_untrusted

    if not rows:
        return (
            f"No web results came back for '{query}'. "
            "Tell the user you could not reach search right now; do not open more tabs."
        )
    lines = [f"Search results for '{query}':"]
    for i, row in enumerate(rows, 1):
        title = row.get("title") or "(untitled)"
        snippet = row.get("snippet") or ""
        inj = apply_injection(f"{title}\n{snippet}", audit_tool="research_fetch_scan")
        if inj.blocked:
            lines.append(f"{i}. [blocked untrusted page content]")
            continue
        lines.append(f"{i}. {title}")
        if snippet:
            lines.append(f"   {snippet}")
        if row.get("url"):
            lines.append(f"   {row['url']}")
    body = "\n".join(lines)
    # Fenced data only — never append exam-style "brief the user" lines; those teach
    # models to emit "Input context / Provided data (from a mock web_search)" theater.
    return fence_untrusted(body, source=f"web_search:{query}")


def perform_knowledge_search(query: str, *, open_browser: bool = False) -> KnowledgeNote:
    """Return titles/snippets. Opens a tab only if fetch failed and open_browser=True."""
    global _last_key

    raw = (query or "").strip()
    query = clean_web_query(raw) or raw
    if query != raw:
        print(f"[Knowledge] Query cleaned: {raw!r} → {query!r}", flush=True)
    key = _norm(query)
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < _CACHE_TTL:
        print(f"[Knowledge] Reusing results for: {query}", flush=True)
        _last_key = key
        return hit[1]

    print(f"[Knowledge] Searching: {query}", flush=True)
    rows = fetch_web_results(query)
    summary = format_results(query, rows)
    if not rows and open_browser:
        url = "https://www.google.com/search?q=" + urllib.parse.quote_plus(query)
        try:
            import webbrowser

            webbrowser.open(url)
        except Exception:  # noqa: BLE001
            pass
        summary = (
            f"Could not fetch results for '{query}', opened one search tab as a fallback. "
            "Read the visible results once, then answer; do not open another tab."
        )
    note = KnowledgeNote(query=query, summary=summary, source="web_search")
    _cache[key] = (now, note, rows)
    _last_key = key
    print(f"[Knowledge] {len(rows)} result(s)", flush=True)
    return note
