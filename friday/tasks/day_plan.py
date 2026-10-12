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
        from friday.calendar import agenda as cal

        block = cal.today_agenda()
        # today_agenda may return dict or string depending on implementation
        if isinstance(block, dict):
            events = block.get("events") or block.get("items") or []
            lines = []
            for ev in events[:12]:
                if isinstance(ev, dict):
                    title = ev.get("summary") or ev.get("title") or "Event"
                    when = (ev.get("start") or "")[:16].replace("T", " ")
                    lines.append(f"{when} — {title}".strip(" —") if when else str(title))
                else:
                    lines.append(str(ev)[:120])
            return lines
        if isinstance(block, str) and block.strip() and "no" not in block.lower()[:20]:
            return [ln.strip() for ln in block.splitlines() if ln.strip()][:12]
    except Exception:  # noqa: BLE001
        pass
    return []


def compose_day_plan_reply(*, user_text: str = "") -> dict[str, Any]:
    """Scrub junk, summarize calendar + open items, propose a concrete day outline."""
    scrubbed = scrub_meta_items()
    from friday.tasks.plan import format_for_prompt, get_plan

    data = get_plan()
    open_items = [it for it in (data.get("items") or []) if not it.get("done")]
    cal = _calendar_lines()

    sections: list[str] = []
    if cal:
        sections.append("Calendar today:\n" + "\n".join(f"• {c}" for c in cal))
    else:
        sections.append("Calendar today: (no events loaded — secret iCal optional).")

    if open_items:
        sections.append("Already on your Friday agenda:\n" + format_for_prompt())
    else:
        sections.append("Friday agenda: empty — good canvas.")

    # Prefer a short local model outline; fall back to a template.
    outline = _model_outline(user_text=user_text, calendar=cal, open_items=open_items)
    if not outline:
        outline = _template_outline(calendar=cal, open_items=open_items)

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
