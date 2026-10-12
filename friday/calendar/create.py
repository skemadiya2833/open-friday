"""Create events via Google Calendar template URLs and .ics files (never auto-submit)."""

from __future__ import annotations

import shutil
import subprocess
import webbrowser
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote


def _format_gcal_date(dt: datetime, all_day: bool) -> str:
    if all_day:
        return dt.strftime("%Y%m%d")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.now().astimezone().tzinfo)
    utc = dt.astimezone(timezone.utc)
    return utc.strftime("%Y%m%dT%H%M%SZ")


def build_template_url(
    text: str,
    start: datetime,
    end: datetime,
    *,
    details: str = "",
    location: str = "",
    guests: list[str] | None = None,
    all_day: bool = False,
    ctz: str | None = None,
) -> str:
    base = "https://calendar.google.com/calendar/render?action=TEMPLATE"
    dates = f"{_format_gcal_date(start, all_day)}/{_format_gcal_date(end, all_day)}"
    params = [
        ("text", text),
        ("dates", dates),
        ("details", details),
        ("location", location),
    ]
    if ctz:
        params.append(("ctz", ctz))
    q = "&".join(f"{k}={quote(v)}" for k, v in params if v)
    url = f"{base}&{q}"
    if guests:
        for g in guests:
            g = g.strip()
            if g:
                url += f"&add={quote(g)}"
    return url


def write_ics(
    path: str | Path,
    *,
    uid: str,
    summary: str,
    start: datetime,
    end: datetime,
    description: str = "",
    location: str = "",
    all_day: bool = False,
) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if all_day:
        ds = start.strftime("%Y%m%d")
        de = end.strftime("%Y%m%d")
        dt_lines = f"DTSTART;VALUE=DATE:{ds}\r\nDTEND;VALUE=DATE:{de}\r\n"
    else:
        ds = start.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        de = end.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        dt_lines = f"DTSTART:{ds}\r\nDTEND:{de}\r\n"
    body = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//Friday//Calendar//EN\r\n"
        "BEGIN:VEVENT\r\n"
        f"UID:{uid}\r\n"
        f"SUMMARY:{summary}\r\n"
        f"{dt_lines}"
        f"DESCRIPTION:{description.replace(chr(10), '\\n')}\r\n"
        f"LOCATION:{location}\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
    p.write_text(body, encoding="utf-8", newline="")
    return p


def _find_chrome() -> str | None:
    for name in ("chrome.exe", "google-chrome", "google-chrome-stable", "chromium"):
        found = shutil.which(name)
        if found:
            return found
    for candidate in (
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    ):
        if candidate.is_file():
            return str(candidate)
    return None


def open_in_chrome(url: str) -> dict[str, Any]:
    """Open URL in a new Chrome tab (never navigate the active Friday tab).

    Uses ``--new-tab`` so an existing Chrome window keeps the HUD page and opens
    the target beside it. Falls back to ``webbrowser.open(..., new=2)``.
    """
    chrome = _find_chrome()
    if chrome:
        # --new-tab is required: bare ``chrome.exe <url>`` can replace the
        # foreground tab (often the Friday HUD) on Windows.
        subprocess.Popen(  # noqa: S603
            [chrome, "--new-tab", url],
            close_fds=True,
        )
        return {"opened": True, "browser": "chrome", "url": url, "new_tab": True}
    webbrowser.open(url, new=2)
    return {"opened": True, "browser": "default", "url": url, "new_tab": True}


def google_calendar_day_url(day: date | None = None) -> str:
    d = day or date.today()
    return f"https://calendar.google.com/calendar/r/day/{d.year}/{d.month}/{d.day}"


def google_calendar_week_url(day: date | None = None) -> str:
    d = day or date.today()
    return f"https://calendar.google.com/calendar/r/week/{d.year}/{d.month}/{d.day}"


def google_calendar_agenda_url() -> str:
    return "https://calendar.google.com/calendar/r/agenda"
