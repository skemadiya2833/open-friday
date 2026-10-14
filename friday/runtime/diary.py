"""Daily diary — plain markdown narrative of what Friday did with the owner.

Inspired by capable desktop assistants that keep a day log for continuity.
Deterministic / offline — no LLM required. Feeds morning briefing + chat context.
"""

from __future__ import annotations

import os
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


def continuity_blurb(limit: int = 4) -> str:
    """One short block for system prompts: what was happening recently."""
    bits: list[str] = []
    today = read()
    if today:
        recent = []
        for line in today.splitlines():
            s = line.strip()
            if s and not s.startswith("#"):
                recent.append(s[:100])
            if len(recent) >= limit:
                break
        if recent:
            bits.append("Today so far: " + "; ".join(recent))
    y = yesterday_highlights(limit)
    if y:
        bits.append("Yesterday: " + "; ".join(y))
    if not bits:
        return ""
    return "Session continuity (from diary — use naturally, do not recite):\n- " + "\n- ".join(bits)
