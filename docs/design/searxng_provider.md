# Optional SearXNG search provider (Stage W8 — design only)

## Status

**Off by default. Not installed by this stage.** Interface sketch only.

## Why

Friday’s current research fetch uses DuckDuckGo HTML / Google News RSS through `friday.knowledge.search`. A self-hosted [SearXNG](https://docs.searxng.org/) instance would give the owner a meta-search aggregator without shipping API keys to cloud search vendors.

## Config (proposed)

```env
# FRIDAY_SEARCH_PROVIDER=builtin   # default
# FRIDAY_SEARCH_PROVIDER=searxng
# FRIDAY_SEARXNG_URL=http://127.0.0.1:8080
# FRIDAY_SEARXNG_KEY=              # optional if instance requires it
```

## Interface

```python
class SearchProvider(Protocol):
    def search(self, query: str, *, limit: int = 8) -> list[dict[str, str]]:
        """Return [{title, url, snippet}, ...] — SSRF guard applied to each URL before fetch."""
```

`builtin` keeps today’s behavior. `searxng` would GET `{FRIDAY_SEARXNG_URL}/search?q=...&format=json` on loopback/LAN only, then map results into the same shape. Stage V3 SSRF + content scanners still wrap every subsequent page fetch.

## Owner steps (when they want it)

1. Install SearXNG themselves (Docker or OS package) — Friday will not run an installer.
2. Bind it to localhost; disable public open-proxy settings.
3. Set `FRIDAY_SEARCH_PROVIDER=searxng` and `FRIDAY_SEARXNG_URL`.
4. Restart Friday; run a quick research report and confirm sources appear.

## Privacy trade-off

Queries leave Friday’s process for the SearXNG host. If that host is local, risk stays on-LAN; if remote, the operator sees every research query.
