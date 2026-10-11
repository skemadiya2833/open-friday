"""Rule-based source credibility tags — clearly labelled as heuristic."""

from __future__ import annotations

from urllib.parse import urlparse

_HIGH = {
    "wikipedia.org",
    "gov",
    "edu",
    "arxiv.org",
    "nature.com",
    "science.org",
    "nih.gov",
    "who.int",
    "bbc.com",
    "reuters.com",
    "apnews.com",
}
_LOW = {
    "blogspot.",
    "wordpress.com",
    "medium.com",
    "pastebin.com",
    "bit.ly",
    "t.me",
}


def credibility_for(url: str, title: str = "") -> dict:
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    tag = "unknown"
    if any(host == h or host.endswith("." + h) or h in host for h in _HIGH if "." in h):
        tag = "high"
    elif host.endswith(".gov") or host.endswith(".edu") or host.endswith(".mil"):
        tag = "high"
    elif any(x in host for x in _LOW):
        tag = "low"
    elif host:
        tag = "medium"
    return {
        "tag": tag,
        "label": f"heuristic:{tag} (rule-based; not a fact-check)",
        "heuristic": True,
    }
