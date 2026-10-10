"""Agentic reminders: parse natural language locally, schedule without asking, deliver as notifications.

No model call is needed for the common phrasings ("remind me to call mum in 20 minutes", "every weekday at 9 ...").
Anything the parser cannot read falls back to one strict-JSON model call; if that also fails the assistant asks
ONE short question instead of dumping tool JSON.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from friday.config import TASKS_DB, ensure_data_dirs

_DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_CRON_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_UNIT = {"second": 1, "sec": 1, "minute": 60, "min": 60, "hour": 3600, "hr": 3600, "day": 86400, "week": 604800}
_NUM_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
              "nine": 9, "ten": 10, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "sixty": 60}

INTENT = re.compile(
    r"\b(remind (me|us)|reminder|set (an? )?(alarm|timer|reminder)|alarm (for|at)|timer for|wake me|notify me|ping me|"
    r"schedule (an? |the |this |that )?(task|reminder|job|call|meeting)?|don'?t let me forget|"
    r"add (an? )?(reminder|alarm|timer)|create (an? )?(reminder|alarm|timer)|"
    r"every (day|morning|evening|night|weekday|weekdays|week|hour|minute|monday|tuesday|wednesday|thursday|friday|saturday|sunday|\d+ (minutes?|hours?)))\b",
    re.I,
)

ASKED_WHEN = re.compile(r"when should I (remind|schedule)|what time|say something like", re.I)


@dataclass
class When:
    run_at: float | None
    cron: str | None
    span: tuple[int, int]
    label: str


def _num(tok: str) -> float | None:
    tok = tok.lower()
    if tok in _NUM_WORDS:
        return float(_NUM_WORDS[tok])
    try:
        return float(tok)
    except ValueError:
        return None


_TIME = r"(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<ap>a\.?m\.?|p\.?m\.?)?"
_PARTS = {"morning": (9, 0), "noon": (12, 0), "afternoon": (15, 0), "evening": (18, 0), "tonight": (20, 0), "night": (21, 0)}


def _clock(m: re.Match[str]) -> tuple[int, int, bool] | None:
    """-> (hour, minute, ambiguous). ambiguous = no am/pm given and the hour could be either."""
    h = int(m.group("h"))
    mi = int(m.group("m") or 0)
    ap = (m.group("ap") or "").replace(".", "").lower()
    amb = False
    if ap == "pm" and h < 12:
        h += 12
    elif ap == "am" and h == 12:
        h = 0
    elif not ap and 1 <= h <= 12:
        amb = True
    return (h, mi, amb) if 0 <= h < 24 and 0 <= mi < 60 else None


def parse_when(text: str, now: datetime | None = None) -> When | None:
    now = now or datetime.now()
    t = text.lower()

    # ---- recurring
    m = re.search(r"\bevery\s+(?:(\d+)\s+)?(minutes?|hours?)\b", t)
    if m:
        n = int(m.group(1) or 1)
        if m.group(2).startswith("minute") and 1 <= n < 60:
            return When(None, f"*/{n} * * * *", m.span(), f"every {n} minute(s)")
        if m.group(2).startswith("hour") and 1 <= n < 24:
            return When(None, f"0 */{n} * * *", m.span(), f"every {n} hour(s)")
    m = re.search(r"\b(?:every|each)\s+(day|morning|evening|night|weekdays?|week|" + "|".join(_DAYS) + r")\b(?:\s+(?:at|around)\s+" + _TIME + ")?", t) \
        or re.search(r"\b(daily)\b(?:\s+(?:at|around)\s+" + _TIME + ")?", t)
    if m:
        word = m.group(1)
        hm = None
        if m.groupdict().get("h"):
            c = _clock(m)
            hm = (c[0] + (12 if c[2] and c[0] < 7 else 0), c[1]) if c else None
        else:
            hm = _PARTS.get(word, (9, 0))
        if hm:
            dow = "*"
            if word in ("weekday", "weekdays"):
                dow = "mon-fri"
            elif word in _DAYS:
                dow = _CRON_DAYS[_DAYS.index(word)]
            elif word == "week":
                dow = _CRON_DAYS[now.weekday()]
            return When(None, f"{hm[1]} {hm[0]} * * {dow}", m.span(), f"every {word} at {hm[0]:02d}:{hm[1]:02d}")

    # ---- relative: "in 20 minutes", "in an hour", "for 10 minutes" (timers)
    m = re.search(r"\b(?:in|after|for)\s+(?:about\s+)?(half an?|\w+)\s*(hour|hr|minute|min|second|sec|day|week)s?\b", t)
    if m:
        if m.group(1).startswith("half"):
            n = 0.5
        else:
            n = _num(m.group(1))
        if n is not None and n > 0:
            secs = n * _UNIT[m.group(2)]
            return When(time.time() + secs, None, m.span(), f"in {int(secs // 60) if secs >= 60 else int(secs)} {'min' if secs >= 60 else 's'}")

    # ---- absolute: optional day word + clock / part of day
    day_off, day_span = None, None
    dm = re.search(r"\b(day after tomorrow|tomorrow|today|tonight)\b", t)
    if dm:
        day_off = {"tomorrow": 1, "today": 0, "tonight": 0, "day after tomorrow": 2}[dm.group(1)]
        day_span = dm.span()
    wm = re.search(r"\b(?:on|next|this)?\s*(" + "|".join(_DAYS) + r")\b", t)
    if wm and day_off is None:
        want = _DAYS.index(wm.group(1))
        day_off = (want - now.weekday()) % 7 or 7
        day_span = wm.span()
    cm = re.search(r"\b(?:at|by|around|@)\s*" + _TIME, t)
    clk = _clock(cm) if cm else None
    span = cm.span() if cm else None
    amb = False
    hm: tuple[int, int] | None = None
    if clk:
        hm, amb = (clk[0], clk[1]), clk[2]
    if hm is None:
        pm = re.search(r"\b(morning|noon|afternoon|evening|tonight|night)\b", t)
        if pm and (day_off is not None or pm.group(1) == "tonight"):
            hm = _PARTS[pm.group(1)]
            span = pm.span()
    if hm is None:
        return None

    def at(day: int, hour: int) -> datetime:
        return (now + timedelta(days=day)).replace(hour=hour, minute=hm[1], second=0, microsecond=0)

    if day_off is not None:
        h = hm[0] + (12 if amb and hm[0] < 7 else 0)         # "tomorrow at 5" -> 17:00, "tomorrow at 9" -> 09:00
        base = at(day_off, h)
    elif amb:
        cands = [at(0, hm[0] % 12), at(0, hm[0] % 12 + 12), at(1, hm[0] % 12)]
        base = next(c for c in cands if c > now)               # the next time that clock reading occurs
    else:
        base = at(0, hm[0])
        if base <= now:
            base += timedelta(days=1)
    lo = min(s[0] for s in (span, day_span) if s)
    hi = max(s[1] for s in (span, day_span) if s)
    return When(base.timestamp(), None, (lo, hi), base.strftime("%a %d %b %H:%M"))


_LEAD = re.compile(
    r"^\s*(?:(?:hey|ok|okay)\s+)?(?:friday[,:]?\s*)?(?:please\s+|can you\s+|could you\s+)?"
    r"(?:remind (?:me|us)(?:\s+(?:to|about|that|of))?|set (?:an? )?(?:reminder|alarm|timer)(?:\s+(?:to|for|about|that))?|"
    r"schedule (?:an? |the )?(?:task|reminder|job)?\s*(?:to|for)?|wake me(?:\s+up)?(?:\s+to)?|notify me(?:\s+to)?|ping me(?:\s+to)?|"
    r"don'?t let me forget(?:\s+to)?)\s*", re.I)


def make_title(text: str, when: When) -> str:
    t = text[: when.span[0]] + " " + text[when.span[1]:]
    t = _LEAD.sub("", t.strip(), count=1)
    t = re.sub(r"\b(?:at|on|by|in|every|each|for)\s*$", "", t.strip(" ,.-"), flags=re.I)
    t = re.sub(r"\s+", " ", t).strip(" ,.-")
    t = re.sub(r"^(?:to|that|about)\s+", "", t, flags=re.I)
    return (t[:1].upper() + t[1:]) if t else "Reminder"


# ------------------------------------------------------------------ notifications store
def _conn() -> sqlite3.Connection:
    ensure_data_dirs()
    c = sqlite3.connect(TASKS_DB, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS notifications (
        id TEXT PRIMARY KEY, job_id TEXT, title TEXT, body TEXT, kind TEXT,
        created_at REAL, seen INTEGER DEFAULT 0)""")
    return c


def add_notification(title: str, body: str = "", *, job_id: str = "", kind: str = "reminder", toast: bool = True) -> dict[str, Any]:
    nid = uuid.uuid4().hex[:12]
    row = {"id": nid, "job_id": job_id, "title": title[:200], "body": body[:1500], "kind": kind,
           "created_at": time.time(), "seen": 0}
    with _conn() as c:
        c.execute("INSERT INTO notifications VALUES (?,?,?,?,?,?,?)", tuple(row.values()))
    if toast:
        try:
            from friday.notify import toast as _toast
            from friday.notify import ui_url

            _toast("Friday · " + ("Reminder" if kind == "reminder" else "Task update"), title + (f"\n{body[:140]}" if body else ""), ui_url(nid))
        except Exception as exc:  # noqa: BLE001
            print(f"[Notify] {exc}")
    print(f"[Reminder] {title}")
    return row


def list_notifications(unseen_only: bool = False, limit: int = 50) -> list[dict[str, Any]]:
    with _conn() as c:
        q = "SELECT * FROM notifications " + ("WHERE seen=0 " if unseen_only else "") + "ORDER BY created_at DESC LIMIT ?"
        return [dict(r) for r in c.execute(q, (limit,)).fetchall()]


def get_notification(nid: str) -> dict[str, Any] | None:
    with _conn() as c:
        r = c.execute("SELECT * FROM notifications WHERE id=?", (nid,)).fetchone()
    return dict(r) if r else None


def mark_seen(nid: str | None = None) -> int:
    with _conn() as c:
        cur = c.execute("UPDATE notifications SET seen=1 WHERE seen=0" + (" AND id=?" if nid else ""), (nid,) if nid else ())
        return cur.rowcount


def clear_notifications() -> None:
    with _conn() as c:
        c.execute("DELETE FROM notifications")


# ------------------------------------------------------------------ scheduling
def is_reminder_request(text: str) -> bool:
    return bool(INTENT.search(text or ""))


def _llm_extract(text: str, now: datetime) -> When | None:
    from friday.models.local import query_model_text

    prompt = (
        f"Now is {now.strftime('%A %Y-%m-%d %H:%M')}. Extract the reminder from the request.\n"
        'Reply with ONLY JSON: {"when_iso":"YYYY-MM-DDTHH:MM:SS" or null,"cron":"m h dom mon dow" or null,"title":"short"}\n'
        f"Request: {text}"
    )
    res = query_model_text(prompt, format_json=False, reasoning_mode=False, num_predict=120, num_ctx=1024)
    raw = (res.get("message") or res.get("raw") or "")
    s, e = raw.find("{"), raw.rfind("}")
    if s < 0 or e <= s:
        return None
    try:
        d = json.loads(raw[s:e + 1])
    except json.JSONDecodeError:
        return None
    if d.get("cron") and len(str(d["cron"]).split()) == 5:
        return When(None, str(d["cron"]), (0, 0), f"cron {d['cron']}")
    if d.get("when_iso"):
        try:
            ts = datetime.fromisoformat(str(d["when_iso"])).timestamp()
        except ValueError:
            return None
        if ts > time.time():
            return When(ts, None, (0, 0), datetime.fromtimestamp(ts).strftime("%a %d %b %H:%M"))
    return None


def schedule_from_text(text: str, *, use_llm: bool = True) -> dict[str, Any] | None:
    """Create the reminder immediately. Returns {"job":..., "when":..., "title":..., "reply":...} or None if no time found."""
    now = datetime.now()
    when = parse_when(text, now)
    title = ""
    if when is not None:
        title = make_title(text, when)
    elif use_llm and re.search(r"\b(at|in|on|every|each|tomorrow|tonight|today|next|morning|evening|noon|night|am|pm|daily|weekly|\d)\b", text, re.I):
        try:
            when = _llm_extract(text, now)
        except Exception as exc:  # noqa: BLE001
            print(f"[Reminder] model extraction failed: {exc}")
        if when is not None:
            title = _LEAD.sub("", text.strip(), count=1).strip(" .,") or "Reminder"
    if when is None:
        return None
    from friday.tasks.scheduler import get_scheduler

    job = get_scheduler().add_job(prompt=title, skill_id="reminder", run_at=when.run_at, cron=when.cron, title=title[:80])
    reply = f"Done, boss. I'll remind you: {title} ({when.label})."
    return {"job": job, "when": when.label, "title": title, "reply": reply}
