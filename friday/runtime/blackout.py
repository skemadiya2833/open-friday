"""Blackout — local-only privacy mode (Systems → Safety).

When on: web research and outbound network tools are blocked.
LLM stays on whatever local stack the owner already runs (Ollama).
"""

from __future__ import annotations

_NETWORK_TOOLS = frozenset({
    "web_search",
    "browse",
    "http_get",
    "fetch_url",
})


def enabled() -> bool:
    try:
        from friday.runtime.prefs import get as pref

        return bool(pref("blackout"))
    except Exception:  # noqa: BLE001
        return False


def blocks_tool(name: str) -> bool:
    if not enabled():
        return False
    n = (name or "").strip().lower()
    return n in _NETWORK_TOOLS or n.startswith("web_") or n.startswith("browse_")


def blocks_research() -> bool:
    return enabled()
