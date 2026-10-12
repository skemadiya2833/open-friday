"""Fetch iCal feed with conditional GET and local cache."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from friday.atomic import write_text_atomic
from friday.calendar.secrets import get_ical_url, redact_url
from friday.config import DATA_DIR, ensure_data_dirs

log = logging.getLogger(__name__)

_TIMEOUT = 15
_CACHE_NAME = "calendar_cache.json"


def _cache_path() -> Path:
    ensure_data_dirs()
    return Path(DATA_DIR) / _CACHE_NAME


def _load_cache() -> dict[str, Any]:
    p = _cache_path()
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_cache(data: dict[str, Any]) -> None:
    safe = {
        "etag": data.get("etag"),
        "last_modified": data.get("last_modified"),
        "body": data.get("body"),
        "fetched_at": data.get("fetched_at"),
    }
    write_text_atomic(_cache_path(), json.dumps(safe, indent=2))


def fetch_ical(*, force: bool = False) -> tuple[str, bool]:
    """Return (ics_body, from_cache). Raises RuntimeError with redacted message on failure."""
    url = get_ical_url()
    if not url:
        raise RuntimeError("Calendar iCal URL is not configured")

    cache = _load_cache()
    headers: dict[str, str] = {"User-Agent": "Friday/1.0 (calendar)"}
    if not force:
        if cache.get("etag"):
            headers["If-None-Match"] = str(cache["etag"])
        if cache.get("last_modified"):
            headers["If-Modified-Since"] = str(cache["last_modified"])

    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:  # noqa: S310
            body = resp.read().decode("utf-8", errors="replace")
            etag = resp.headers.get("ETag")
            lm = resp.headers.get("Last-Modified")
            cache.update(
                {
                    "body": body,
                    "etag": etag,
                    "last_modified": lm,
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            _save_cache(cache)
            return body, False
    except urllib.error.HTTPError as exc:
        if exc.code == 304 and cache.get("body"):
            return str(cache["body"]), True
        raise RuntimeError(f"Calendar fetch failed ({exc.code}) for {redact_url(url)}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Calendar fetch failed for {redact_url(url)}: {exc.reason}") from exc
    except TimeoutError as exc:
        raise RuntimeError(f"Calendar fetch timed out for {redact_url(url)}") from exc
    except OSError as exc:
        raise RuntimeError(f"Calendar fetch error for {redact_url(url)}: {exc}") from exc


def cached_body() -> str | None:
    c = _load_cache()
    b = c.get("body")
    return str(b) if b else None


def clear_cache() -> None:
    p = _cache_path()
    if p.is_file():
        try:
            p.unlink()
        except OSError:
            pass
