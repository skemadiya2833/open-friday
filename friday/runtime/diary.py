"""Daily diary — plain markdown narrative of what Friday did with the owner.

Inspired by capable desktop assistants that keep a day log for continuity.
Deterministic / offline — no LLM required. Feeds morning briefing + chat context.
"""

from __future__ import annotations

import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path


def _dir() -> Path:
    from friday.config import DATA_DIR

    path = Path(os.environ.get("FRIDAY_DIARY_DIR") or Path(DATA_DIR) / "diary")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _path(day: date | None = None) -> Path:
    return _dir() / f"{(day or date.today()).isoformat()}.md"


def record(title: str, body: str = "", *, kind: str = "note", day: date | None = None) -> str:
    """Append an entry. Returns the diary file path."""
    path = _path(day)
    stamp = datetime.now().strftime("%H:%M")
    title = (title or "").strip() or "Note"
    body = (body or "").strip()
    block = [f"## {stamp} — {kind}", "", title]
    if body:
        block.extend(["", body])
    block.append("")
    with path.open("a", encoding="utf-8") as f:
        f.write("\n".join(block) + "\n")
    return str(path)


def read(day: date | None = None) -> str:
    path = _path(day)
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def yesterday_highlights(limit: int = 6) -> list[str]:
    """Short titles from yesterday's diary for briefing / continuity."""
    text = read(date.today() - timedelta(days=1))
    if not text:
        return []
    titles: list[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            # "## HH:MM — kind" then next non-empty line is title
            continue
        s = line.strip()
        if s and not s.startswith("#") and s not in titles:
            titles.append(s[:120])
        if len(titles) >= limit:
            break
    return titles


_ASSIST_INVENT = re.compile(
    r"(?i)\b("
    r"i'?ve noted|i noted|it'?s now on your agenda|anything else you'?d like|"
    r"review quarterly|financial reports?|q[1-4]\b|margins?|auditor|line items?|"
    r"market volatility|bleeding through|flagged .{0,20} line"
    r")\b"
)


def _owner_titles_from_markdown(text: str, *, limit: int) -> list[str]:
    """Titles only (first line after each ## header) — never reinject assistant bodies."""
    titles: list[str] = []
    expect_title = False
    for line in text.splitlines():
        if line.startswith("## "):
            expect_title = True
            continue
        s = line.strip()
        if not expect_title or not s or s.startswith("#") or s.startswith("("):
            continue
        expect_title = False
        if _ASSIST_INVENT.search(s):
            continue
        # Skip pure meta capture requests — they aren't facts about the day.
        if re.search(r"(?i)\b(note|write|jot|take)\s*(down)?\s+(my\s+)?(tasks?|to-?dos?|agenda)\b", s):
            continue
        if s not in titles:
            titles.append(s[:120])
        if len(titles) >= limit:
            break
    return titles


def continuity_blurb(limit: int = 4) -> str:
    """One short block for system prompts: owner-facing diary titles only.

    Assistant affirmations must never re-enter the prompt — that caused Q3/margins
    roleplay after a poisoned ``plan_add``.
    """
    bits: list[str] = []
    today = read()
    if today:
        recent = _owner_titles_from_markdown(today, limit=limit)
        if recent:
            bits.append("Today so far: " + "; ".join(recent))
    y = [
        t
        for t in yesterday_highlights(limit * 2)
        if not _ASSIST_INVENT.search(t)
        and not re.search(
            r"(?i)\b(note|write|jot|take)\s*(down)?\s+(my\s+)?(tasks?|to-?dos?|agenda)\b", t
        )
    ][:limit]
    if y:
        bits.append("Yesterday: " + "; ".join(y))
    if not bits:
        return ""
    return (
        "Session continuity (owner diary titles only — never invent work products, "
        "metrics, open documents, or sign-off theater from these lines):\n- "
        + "\n- ".join(bits)
    )
