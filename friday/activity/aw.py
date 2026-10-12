"""Read-only ActivityWatch localhost API client (owner installs AW separately)."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from friday.config import DATA_DIR, ensure_data_dirs

DEFAULT_AW_BASE = "http://127.0.0.1:5600"
_TIMEOUT = 4.0


def _rules_path() -> Path:
    ensure_data_dirs()
    return Path(DATA_DIR) / "aw_rules.json"


def load_approved_rules() -> list[dict[str, Any]]:
    p = _rules_path()
    if not p.is_file():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []
    rules = data.get("rules") if isinstance(data, dict) else []
    out: list[dict[str, Any]] = []
    for r in rules or []:
        if not isinstance(r, dict):
            continue
        if r.get("approved") is True and (r.get("keyword") or "").strip():
            out.append(r)
    return out


def save_rules(rules: list[dict[str, Any]]) -> None:
    from friday.atomic import write_text_atomic

    ensure_data_dirs()
    payload = {"rules": rules, "updated_at": datetime.now(timezone.utc).isoformat()}
    write_text_atomic(_rules_path(), json.dumps(payload, indent=2))


def approve_rules(suggestions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Persist owner-approved keyword categorization rules."""
    existing = {r.get("keyword", "").lower(): r for r in load_approved_rules()}
    for s in suggestions:
        kw = (s.get("keyword") or "").strip()
        if not kw:
            continue
        existing[kw.lower()] = {
            "keyword": kw,
            "category": (s.get("category") or "other").strip() or "other",
            "approved": True,
        }
    merged = list(existing.values())
    save_rules(merged)
    return merged


@dataclass
class ActivityWatchClient:
    base_url: str = DEFAULT_AW_BASE

    def _url(self, path: str, *, query: dict[str, str] | None = None) -> str:
        base = self.base_url.rstrip("/")
        p = path if path.startswith("/") else f"/{path}"
        if query:
            p = f"{p}?{urllib.parse.urlencode(query)}"
        return f"{base}{p}"

    def _get_json(self, path: str, *, query: dict[str, str] | None = None) -> Any:
        req = urllib.request.Request(
            self._url(path, query=query),
            headers={"Accept": "application/json"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def probe(self) -> dict[str, Any]:
        """Return availability and server info when AW is running."""
        try:
            info = self._get_json("/api/0/info")
            return {"available": True, "info": info}
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, ValueError):
            return {"available": False, "info": None}

    def list_buckets(self) -> dict[str, Any]:
        st = self.probe()
        if not st["available"]:
            return {"available": False, "buckets": {}}
        buckets = self._get_json("/api/0/buckets/")
        return {"available": True, "buckets": buckets or {}}

    def fetch_events(
        self,
        bucket_id: str,
        *,
        start: datetime,
        end: datetime,
    ) -> list[dict[str, Any]]:
        st = self.probe()
        if not st["available"]:
            return []
        q = {
            "start": start.astimezone(timezone.utc).isoformat(),
            "end": end.astimezone(timezone.utc).isoformat(),
        }
        try:
            raw = self._get_json(f"/api/0/buckets/{urllib.parse.quote(bucket_id, safe='')}/events", query=q)
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, ValueError):
            return []
        return list(raw) if isinstance(raw, list) else []

    def fetch_window_events(
        self,
        *,
        start: datetime,
        end: datetime,
        bucket_substr: str = "aw-watcher-window",
    ) -> list[dict[str, Any]]:
        """Collect window-title events from matching buckets."""
        bk = self.list_buckets()
        if not bk.get("available"):
            return []
        events: list[dict[str, Any]] = []
        for bid in (bk.get("buckets") or {}).keys():
            if bucket_substr not in bid:
                continue
            events.extend(self.fetch_events(bid, start=start, end=end))
        events.sort(key=lambda e: float(e.get("timestamp") or 0))
        return events


def normalize_aw_event(ev: dict[str, Any], *, rules: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Map AW window event to unified sample shape."""
    rules = rules if rules is not None else load_approved_rules()
    data = ev.get("data") if isinstance(ev.get("data"), dict) else {}
    app = str(data.get("app") or data.get("program") or "")
    title = str(data.get("title") or "")
    ts = float(ev.get("timestamp") or 0)
    dur = float(ev.get("duration") or 0)
    blob = f"{app} {title}".lower()
    category = "uncategorized"
    for r in rules:
        kw = (r.get("keyword") or "").lower()
        if kw and kw in blob:
            category = r.get("category") or "other"
            break
    return {
        "source": "activitywatch",
        "start": ts,
        "duration": max(0.0, dur),
        "app": app,
        "title": title,
        "category": category,
    }


def suggest_categorization_rules(events: list[dict[str, Any]], *, limit: int = 12) -> list[dict[str, Any]]:
    """Keyword rules for owner approval — not applied until approved."""
    tokens: Counter[str] = Counter()
    for ev in events:
        data = ev.get("data") if isinstance(ev.get("data"), dict) else {}
        for part in (data.get("app"), data.get("title")):
            if not part:
                continue
            for tok in re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{2,}", str(part)):
                low = tok.lower()
                if low in {"the", "and", "for", "windows", "microsoft"}:
                    continue
                tokens[low] += 1
    suggestions: list[dict[str, Any]] = []
    for word, count in tokens.most_common(limit * 2):
        if count < 3:
            break
        cat = _guess_category(word)
        suggestions.append({"keyword": word, "category": cat, "hits": count, "approved": False})
        if len(suggestions) >= limit:
            break
    return suggestions


def _guess_category(word: str) -> str:
    w = word.lower()
    if w in {"zoom", "teams", "meet", "slack", "discord", "outlook"}:
        return "communication"
    if w in {"code", "cursor", "vscode", "visual", "studio", "pycharm", "terminal", "powershell"}:
        return "deep_work"
    if w in {"chrome", "firefox", "edge", "browser"}:
        return "web"
    return "other"
