"""Build a useful 'plan my day' reply — never treat the request itself as an agenda item."""

from __future__ import annotations

import re
from typing import Any

# Utterances that mean "help me plan" — must never be stored as agenda lines.
_META_PLAN = re.compile(
    r"^\s*(hey\s+)?(friday[,:]?\s*)?"
    r"(i was thinking maybe you could\s+)?"
    r"(please\s+)?"
    r"(can you\s+|could you\s+|would you\s+)?"
    r"(help (me )?)?"
    r"(plan|organise|organize|schedule|map out|build|make)\s+"
    r"(my |the |a )?(day|today|agenda|schedule)\b"
    r"|^\s*plan my day\b",
    re.I,
)


def is_meta_plan_request(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if _META_PLAN.search(t):
        return True
    # Short variants
    return bool(
        re.match(
            r"^(plan|organise|organize|schedule)\s+(my\s+)?(day|today)\s*[.!?]*$",
            t,
            re.I,
        )
    )


def extract_agenda_items(text: str) -> list[str]:
    """Pull concrete workstreams out of a voice planning dump (not the whole transcript)."""
    t = (text or "").strip()
    if not t:
        return []
    items: list[str] = []
    low = t.lower()

    if re.search(r"\bcheck on everything|what we('?ve| have) got so far|review (everything|what we)\b", low):
        items.append("Review everything we've got so far")
    if re.search(r"\byoutube\b", low):
        n = 2 if re.search(r"\b(two|2)\b.{0,40}\byoutube\b|\byoutube\b.{0,40}\b(two|2)\b", low) else 1
        items.append("Grow YouTube channel(s)" if n > 1 else "Grow YouTube channel")
    if re.search(r"\binstagram\b", low):
        items.append("Grow Instagram page")
    if re.search(r"\b3d\s*print", low):
        items.append("3D printing business — explore and plan")
    if re.search(r"\btiktok\b", low):
        items.append("Grow TikTok")

    # "we'll be doing X" — take a short clause when we still have nothing specific
    if not items:
        m = re.search(
            r"\bwe('?ll| will) be doing\b\s+(.+?)(?:\s+along with|\s+and then|\.|$)",
            t,
            re.I | re.S,
        )
        if m:
            clause = re.sub(r"\s+", " ", m.group(2)).strip(" ,.-")
            clause = re.split(r"\b(?:uh+|um+)\b", clause, maxsplit=1, flags=re.I)[0].strip(" ,.-")
            if 3 <= len(clause) <= 80:
                items.append(clause[:1].upper() + clause[1:])

    # De-dupe preserve order
    out: list[str] = []
    seen: set[str] = set()
    for it in items:
        key = it.lower()
        if key not in seen:
            seen.add(key)
            out.append(it)
    return out[:8]


def scrub_meta_items() -> int:
    """Remove agenda rows that are clearly planning requests, not real tasks. Returns count removed."""
    from friday.tasks.plan import get_plan, remove_item

    data = get_plan()
    removed = 0
    for it in list(data.get("items") or []):
        if is_meta_plan_request(str(it.get("text") or "")):
            if remove_item(str(it.get("id"))):
                removed += 1
    return removed


def _calendar_lines() -> list[str]:
    try:
        from friday.calendar.cache import today_lines

        return today_lines(force=False, limit=12)
    except Exception:  # noqa: BLE001
        return []


def compose_day_plan_reply(*, user_text: str = "", voice_mode: bool = False) -> dict[str, Any]:
    """Scrub junk, summarize calendar + open items, propose a concrete day outline."""
    scrubbed = scrub_meta_items()
    from friday.tasks.plan import format_for_prompt, get_plan

    data = get_plan()
    open_items = [it for it in (data.get("items") or []) if not it.get("done")]
    cal = _calendar_lines()

    # Prefer a short local model outline; fall back to a template.
    outline = _model_outline(user_text=user_text, calendar=cal, open_items=open_items)
    if not outline:
        outline = _template_outline(calendar=cal, open_items=open_items)

    # Voice: speak the outline only — never dump empty-calendar / setup stubs.
    if voice_mode:
        bits = ["Here's today's outline."]
        if cal:
            bits.append("Calendar: " + "; ".join(cal[:3]) + ".")
        if open_items:
            tops = "; ".join((it.get("text") or "")[:60] for it in open_items[:3])
            bits.append(f"Already on the agenda: {tops}.")
        bits.append(outline.replace("\n", " "))
        bits.append("Say what to lock in and I'll add it.")
        if scrubbed:
            bits.append(f"Cleared {scrubbed} bogus planning line(s).")
        reply = " ".join(bits)
        return {"reply": reply, "scrubbed": scrubbed, "plan": data, "calendar_n": len(cal)}

    sections: list[str] = []
    if cal:
        sections.append("Calendar today:\n" + "\n".join(f"• {c}" for c in cal))
    # Omit empty calendar — setup hints belong in Settings, not the chat reply.

    if open_items:
        sections.append("Already on your Friday agenda:\n" + format_for_prompt())

    sections.append("Proposed day:\n" + outline)
    sections.append(
        "Say what to lock in (e.g. \"add deep work 9–11\" or \"we'll be doing inbox zero this afternoon\") "
        "and I'll put real items on the agenda — I won't save the words \"plan my day\" as a task."
    )
    if scrubbed:
        sections.append(f"(Cleared {scrubbed} bogus agenda line(s) that were just planning requests.)")

    reply = "Here's a working plan for today, boss.\n\n" + "\n\n".join(sections)
    return {"reply": reply, "scrubbed": scrubbed, "plan": data, "calendar_n": len(cal)}


def _template_outline(*, calendar: list[str], open_items: list[dict]) -> str:
    lines = [
        "Morning — clear the must-dos and any calendar anchors.",
        "Midday — one deep block on the highest-leverage open item.",
        "Afternoon — admin, messages, and carry-overs.",
        "EOD — mark done, park the rest for tomorrow.",
    ]
    if open_items:
        top = open_items[0].get("text") or "your top open item"
        lines[1] = f"Midday — deep block on: {top}"
    if calendar:
        lines[0] = f"Morning — respect calendar first ({calendar[0][:80]})."
    return "\n".join(f"• {ln}" for ln in lines)


def _model_outline(*, user_text: str, calendar: list[str], open_items: list[dict]) -> str:
    try:
        from friday.models.local import query_model_text

        open_txt = "; ".join((it.get("text") or "")[:80] for it in open_items[:8]) or "(none)"
        cal_txt = "; ".join(calendar[:8]) or "(none)"
        prompt = (
            "You are Friday. Output ONLY a compact day outline as 4–6 bullet lines. "
            "No preamble. Each line starts with Morning/Midday/Afternoon/EOD or a time. "
            "Use the calendar and open items; do not invent meetings.\n"
            f"Owner said: {user_text[:200]}\n"
            f"Calendar: {cal_txt}\n"
            f"Open agenda: {open_txt}\n"
            "Outline:"
        )
        out = query_model_text(
            prompt,
            format_json=False,
            think=False,
            num_predict=180,
            num_ctx=2048,
        )
        text = (out.get("message") or out.get("raw") or "").strip()
        if not text or "unreachable" in text.lower():
            return ""
        # Keep it short and bullet-like
        lines = [ln.strip(" -•\t") for ln in text.splitlines() if ln.strip()][:8]
        if len(lines) < 2:
            return ""
        return "\n".join(f"• {ln}" for ln in lines)
    except Exception:  # noqa: BLE001
        return ""
