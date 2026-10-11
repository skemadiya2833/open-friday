"""Mechanical citation / chart validation for research reports."""

from __future__ import annotations

import re
from typing import Any

_WS = re.compile(r"\s+")


def norm_ws(text: str) -> str:
    return _WS.sub(" ", (text or "").strip())


def evidence_in_source(evidence: str, source_text: str) -> bool:
    ev = norm_ws(evidence)
    src = norm_ws(source_text)
    if len(ev) < 8:
        return False
    return ev in src


def value_in_snippet(value: float | int, snippet: str) -> bool:
    sn = norm_ws(snippet)
    # Accept integer or common float renderings present as substrings.
    candidates = {str(value), f"{value:g}", f"{float(value):.0f}", f"{float(value):.1f}", f"{float(value):.2f}"}
    return any(c and c in sn for c in candidates)


def validate_mechanics(doc: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Drop or mark unsupported claims; validate charts. Returns (doc, issues)."""
    issues: list[str] = []
    sources = {s["id"]: s for s in (doc.get("sources") or []) if s.get("id")}
    claims_out = []
    for c in doc.get("claims") or []:
        sid = c.get("source_id") or ""
        src = sources.get(sid)
        if not src:
            issues.append(f"claim {c.get('id')}: unknown source_id")
            c = {**c, "supported": False, "marked_unsupported": True}
            claims_out.append(c)
            continue
        ok = evidence_in_source(c.get("evidence") or "", src.get("text") or "")
        if not ok:
            issues.append(f"claim {c.get('id')}: evidence not substring of source")
            c = {**c, "supported": False, "marked_unsupported": True}
        else:
            c = {**c, "supported": True, "marked_unsupported": False}
        claims_out.append(c)

    # Keep supported claims; drop unsupported unless marked for display
    kept = [c for c in claims_out if c.get("supported")]
    dropped = len(claims_out) - len(kept)
    if dropped:
        issues.append(f"dropped {dropped} unsupported claim(s)")

    charts_out = []
    for ch in doc.get("charts") or []:
        series_ok = []
        for pt in ch.get("series") or []:
            sid = pt.get("source_id") or ""
            src = sources.get(sid)
            snip = pt.get("snippet") or ""
            if not src:
                issues.append(f"chart {ch.get('id')}: unknown source for point")
                continue
            if not evidence_in_source(snip, src.get("text") or ""):
                issues.append(f"chart {ch.get('id')}: snippet not in source")
                continue
            if not value_in_snippet(pt.get("value"), snip):
                issues.append(f"chart {ch.get('id')}: value not in snippet")
                continue
            series_ok.append(pt)
        if series_ok:
            charts_out.append({**ch, "series": series_ok})

    # Findings that cite missing sources lose those ids
    findings_out = []
    for f in doc.get("findings") or []:
        sids = [s for s in (f.get("source_ids") or []) if s in sources]
        findings_out.append({**f, "source_ids": sids})

    out = {
        **doc,
        "claims": kept,
        "charts": charts_out,
        "findings": findings_out,
    }
    return out, issues
