"""Persist research reports under data/reports."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from friday.config import DATA_DIR, ensure_data_dirs
from friday.reports.limits import REPORT_RETENTION


def reports_dir() -> Path:
    ensure_data_dirs()
    d = Path(DATA_DIR) / "reports"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _meta_path(rid: str) -> Path:
    return reports_dir() / f"{rid}.json"


def _snap_path(rid: str) -> Path:
    return reports_dir() / f"{rid}.snapshot.json"


def save_report(doc: dict[str, Any], *, snapshot: dict[str, Any] | None = None) -> str:
    from friday.atomic import write_text_atomic
    from friday.security.content_scan import apply_secrets, Mode

    rid = str(doc["id"])
    # Redact secrets before disk
    blob = json.dumps(doc, ensure_ascii=False, indent=2)
    red = apply_secrets(blob, mode=Mode.REDACT, audit_tool="report_store")
    write_text_atomic(_meta_path(rid), red.text)
    if snapshot is not None:
        snap_blob = json.dumps(snapshot, ensure_ascii=False, indent=2)
        snap_red = apply_secrets(snap_blob, mode=Mode.REDACT, audit_tool="report_store")
        write_text_atomic(_snap_path(rid), snap_red.text)
    _enforce_retention()
    return rid


def get_report(rid: str) -> dict[str, Any] | None:
    p = _meta_path(rid)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def list_reports(limit: int = 50) -> list[dict[str, Any]]:
    rows = []
    for p in sorted(reports_dir().glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        if p.name.endswith(".snapshot.json"):
            continue
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        rows.append({
            "id": doc.get("id"),
            "query": doc.get("query"),
            "mode": doc.get("mode"),
            "created_at": doc.get("created_at"),
            "tldr": (doc.get("summary") or {}).get("tldr", "")[:200],
            "fallback_plain": bool(doc.get("fallback_plain")),
        })
        if len(rows) >= limit:
            break
    return rows


def delete_report(rid: str) -> bool:
    ok = False
    for p in (_meta_path(rid), _snap_path(rid)):
        if p.is_file():
            p.unlink(missing_ok=True)
            ok = True
    return ok


def _enforce_retention() -> None:
    files = sorted(
        [p for p in reports_dir().glob("*.json") if not p.name.endswith(".snapshot.json")],
        key=lambda x: x.stat().st_mtime,
        reverse=True,
    )
    for p in files[REPORT_RETENTION:]:
        rid = p.stem
        delete_report(rid)


def export_markdown(doc: dict[str, Any]) -> str:
    lines = [
        f"# Research: {doc.get('query', '')}",
        "",
        f"_Mode: {doc.get('mode')} · {doc.get('created_at')}_",
        "",
        "## TL;DR",
        (doc.get("summary") or {}).get("tldr", ""),
        "",
        f"Confidence: {(doc.get('summary') or {}).get('confidence')} — {(doc.get('summary') or {}).get('rationale', '')}",
        "",
    ]
    if doc.get("fallback_plain"):
        lines += ["", f"> Fallback plain summary: {doc.get('fallback_reason', '')}", ""]
    findings = doc.get("findings") or []
    if findings:
        lines.append("## Key findings")
        for f in findings:
            lines.append(f"### {f.get('title')}")
            lines.append(f.get("body") or "")
            lines.append("")
    claims = doc.get("claims") or []
    if claims:
        lines.append("## Claims")
        for c in claims:
            lines.append(f"- **{c.get('claim')}** (source `{c.get('source_id')}`)")
            lines.append(f"  - Evidence: {c.get('evidence')}")
    sources = doc.get("sources") or []
    if sources:
        lines.append("")
        lines.append("## Sources")
        for s in sources:
            cred = (s.get("credibility") or {}).get("label", "")
            lines.append(f"- [{s.get('domain')}] {s.get('title')} — {s.get('url')} ({cred})")
    return "\n".join(lines)


def export_standalone_html(doc: dict[str, Any]) -> str:
    """Script-free HTML with inline CSS for print/PDF."""
    from html import escape

    mdish = export_markdown(doc)
    # Neutralize dangerous URL schemes even as plain text in the export.
    mdish = re.sub(r"(?i)\bjavascript\s*:", "blocked:", mdish)
    mdish = re.sub(r"(?i)\bdata\s*:", "blocked:", mdish)
    body = "<br>\n".join(escape(line) if line else "<br>" for line in mdish.splitlines())
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Friday report</title>
<style>
body{{font:14px/1.45 Georgia,serif;max-width:48rem;margin:2rem auto;color:#111;background:#fff;padding:1rem}}
h1,h2,h3{{font-family:system-ui,sans-serif}}
@media print{{body{{margin:0;max-width:none}}}}
.muted{{color:#555;font-size:12px}}
</style></head><body>
<p class="muted">Friday research export · no scripts · secrets redacted at save</p>
{body}
</body></html>"""
