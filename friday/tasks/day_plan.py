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


# "Note down my tasks" / "write my todos" — capture intent without naming items yet.
_TASK_CAPTURE = re.compile(
    r"\b("
    r"(note|write|jot|take)\s*(down)?\s+(my\s+)?(tasks?|to-?dos?|agenda|list)\b|"
    r"(note|write|jot|take)\s*(them\s+)?down\b.{0,40}\b(tasks?|to-?dos?|agenda)\b|"
    r"(capture|record|log|save)\s+(my\s+)?(tasks?|to-?dos?|agenda)\b|"
    r"(dictate|give you|tell you)\s+(my\s+)?(tasks?|to-?dos?)\b|"
    r"(tasks?|to-?dos?)\s+(for\s+)?(today|the\s+day)\b"
    r")",
    re.I,
)
ASKED_FOR_TASKS = re.compile(
    r"what should I put on today'?s list|give them one at a time|"
    r"what(?:'s| are) (?:on )?(?:the |your )?tasks|hit me with (?:the |your )?tasks|"
    r"shall I lock|want me to lock|say (?:lock|yes)|lock these in|"
    r"from (?:what I can see|your )?(?:calendar|agenda)?|here's what I(?:'d| would) put|"
    r"I'?d put:|already got .{0,40} on today'?s list",
    re.I,
)


def is_empty_task_capture(text: str) -> bool:
    """True when the owner wants tasks noted but has not named any yet — ask, don't invent."""
    t = (text or "").strip()
    if not t or not _TASK_CAPTURE.search(t):
        return False
    # Listing / showing existing agenda is not capture.
    if re.search(
        r"\b(what('?s| is)|show|list|read)\b.{0,30}\b(plan|agenda|tasks?|to-?dos?)\b",
        t,
        re.I,
    ):
        return False
    if extract_agenda_items(t):
        return False
    # "tasks: buy milk" or numbered list already has payload.
    if re.search(r"[:\-]\s*\S.{2,}", t) and re.search(r"\b(tasks?|to-?dos?|agenda)\b", t, re.I):
        after = re.split(r"[:\-]", t, maxsplit=1)
        if len(after) > 1 and len(after[1].strip()) > 3:
            return False
    if re.search(r"\b(1[\).:]|first[,:]|second[,:]|third[,:])\s+\S", t, re.I):
        return False
    # Strip capture framing + politeness wrappers; leftover substance = they named items.
    stripped = _TASK_CAPTURE.sub(" ", t)
    stripped = re.sub(
        r"(?i)\b("
        r"(hey\s+)?friday|"
        r"please|"
        r"i\s+want\s+you\s+to|i\s+need\s+you\s+to|i'?d\s+like\s+you\s+to|"
        r"can\s+you|could\s+you|would\s+you|will\s+you|"
        r"for\s+me|for\s+today|today|now|"
        r"just|kindly|maybe"
        r")\b",
        " ",
        stripped,
    )
    stripped = re.sub(r"\s+", " ", stripped).strip(" .,!?;:")
    if len(stripped) >= 8:
        return False
    return True


def split_task_dictation(text: str) -> list[str]:
    """Split a follow-up dictation into agenda lines (comma / and / newline / numbered)."""
    t = (text or "").strip()
    if not t:
        return []
    from_extract = extract_agenda_items(t)
    if from_extract:
        return from_extract
    # Numbered or bulleted
    lines = re.findall(r"(?:^|\n)\s*(?:\d+[\).:]|[-•*])\s*(.+)", t)
    if lines:
        return [re.sub(r"\s+", " ", ln).strip(" .,")[:120] for ln in lines if len(ln.strip()) >= 3][:8]
    # Comma / semicolon / " and "
    parts = re.split(r"\s*[;|\n]+\s*|\s*,\s*|\s+and\s+", t, flags=re.I)
    out: list[str] = []
    for p in parts:
        p = re.sub(r"^\s*(\d+[\).:]|[-•*])\s*", "", p)
        p = re.sub(r"\s+", " ", p).strip(" .,")
        if len(p) < 3:
            continue
        if is_meta_plan_request(p) or is_empty_task_capture(p) or parse_lock_in_confirmation(p):
            continue
        if re.match(r"(?i)^(uh+|um+|yeah|ok|okay|sure|thanks|please)$", p):
            continue
        out.append(p[:1].upper() + p[1:] if p else p)
    return out[:8]


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


def gather_day_context() -> dict[str, Any]:
    """What Friday can actually sense for today — not guesses."""
    from friday.tasks.plan import get_plan

    data = get_plan()
    open_items = [it for it in (data.get("items") or []) if not it.get("done")]
    cal = _calendar_lines()
    diary: list[str] = []
    profile = ""
    knowledge: list[str] = []
    try:
        from friday.runtime.diary import continuity_blurb, yesterday_highlights

        diary = list(yesterday_highlights(limit=4) or [])
        if not diary:
            blob = continuity_blurb(limit=4) or ""
            diary = [ln.strip(" -•") for ln in blob.splitlines() if ln.strip().startswith("-")][:4]
    except Exception:  # noqa: BLE001
        pass
    try:
        from friday.runtime.owner_profile import prompt_block

        profile = (prompt_block() or "").strip()[:600]
    except Exception:  # noqa: BLE001
        pass
    try:
        from friday.runtime.knowledge import continuity_lines

        knowledge = list(continuity_lines(limit=4) or [])
    except Exception:  # noqa: BLE001
        pass
    return {
        "plan": data,
        "open_items": open_items,
        "calendar": cal,
        "diary": diary,
        "profile": profile,
        "knowledge": knowledge,
        "has_signal": bool(cal or open_items or diary or knowledge or profile),
    }


def compose_task_capture_reply(*, user_text: str = "", voice_mode: bool = False) -> dict[str, Any]:
    """Note-my-tasks: use senses + model. Propose from evidence, or ask one sharp question — never invent."""
    from friday.persona import owner_name

    ctx = gather_day_context()
    proposed = _model_task_proposals(user_text=user_text, ctx=ctx)
    if not proposed and ctx["calendar"]:
        proposed = [f"Prep / attend: {c}"[:100] for c in ctx["calendar"][:3]]
    if not proposed and ctx["open_items"]:
        # Already have agenda — confirm rather than invent.
        tops = [str(it.get("text") or "")[:80] for it in ctx["open_items"][:4] if it.get("text")]
        if voice_mode:
            reply = (
                f"You've already got {len(tops)} on today's list, {owner_name()}: "
                + "; ".join(tops)
                + ". Want to add more, or lock these?"
            )
        else:
            reply = (
                f"You've already got these on today's list, {owner_name()}:\n"
                + "\n".join(f"• {t}" for t in tops)
                + "\n\nSay what to add, or \"looks good\" if we're set."
            )
        return {
            "reply": reply,
            "awaiting_tasks": True,
            "proposed": [],
            "plan": ctx["plan"],
            "used_senses": True,
        }

    if proposed:
        if voice_mode:
            reply = (
                "From what I can see, I'd put: "
                + "; ".join(proposed[:5])
                + f". Say lock these in, or tell me what to change, {owner_name()}."
            )
        else:
            reply = (
                f"Here's what I'd put on today's list from your calendar, agenda, and recent notes, "
                f"{owner_name()}:\n"
                + "\n".join(f"• {p}" for p in proposed[:6])
                + "\n\nSay **lock these in**, edit any line, or add what I missed."
            )
        return {
            "reply": reply,
            "awaiting_tasks": True,
            "proposed": proposed[:6],
            "plan": ctx["plan"],
            "used_senses": True,
        }

    # No signal — one short question (still intelligence: don't fabricate a day).
    if voice_mode:
        reply = (
            f"I don't have calendar or carry-overs loaded yet, {owner_name()}. "
            "Hit me with the tasks — or say plan my day and I'll sketch from what we do have."
        )
    else:
        reply = (
            f"I don't have much on the board yet, {owner_name()} — no calendar hits or open agenda. "
            "What should go on today's list? Or say **plan my day** and I'll outline from whatever signals we get."
        )
    return {
        "reply": reply,
        "awaiting_tasks": True,
        "proposed": [],
        "plan": ctx["plan"],
        "used_senses": False,
    }


def parse_lock_in_confirmation(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    return bool(
        re.match(
            r"^(yes|yeah|yep|ok|okay|sure|lock( them| these| it)?( in)?|looks good|"
            r"do it|go ahead|that works|perfect|ship it)\s*[.!]?\s*$",
            t,
            re.I,
        )
    )


def extract_proposed_from_assistant(text: str) -> list[str]:
    """Pull bullet / semicolon proposals from Friday's last capture reply."""
    t = (text or "").strip()
    if not t:
        return []
    bullets = re.findall(r"(?:^|\n)\s*[-•*]\s*(.+)", t)
    if bullets:
        return [re.sub(r"\s+", " ", b).strip(" .,")[:120] for b in bullets if len(b.strip()) >= 3][:8]
    m = re.search(
        r"(?:I'?d put|I would put|put on today'?s list)[:\s]+(.+?)(?:\.\s*Say|\.\s*$|$)",
        t,
        re.I | re.S,
    )
    if m:
        chunk = m.group(1)
        # Drop trailing instruction clauses.
        chunk = re.split(r"\bSay\b|\block these\b", chunk, maxsplit=1, flags=re.I)[0]
        parts = re.split(r"\s*;\s*|\s*,\s+and\s+|\s+and\s+", chunk)
        return [
            re.sub(r"\s+", " ", p).strip(" .,")[:120]
            for p in parts
            if len(p.strip()) >= 3 and not parse_lock_in_confirmation(p.strip())
        ][:8]
    return []


def compose_day_plan_reply(*, user_text: str = "", voice_mode: bool = False) -> dict[str, Any]:
    """Scrub junk, summarize calendar + open items, propose a concrete day outline."""
    scrubbed = scrub_meta_items()
    from friday.tasks.plan import format_for_prompt

    ctx = gather_day_context()
    data = ctx["plan"]
    open_items = ctx["open_items"]
    cal = ctx["calendar"]

    # Prefer a short local model outline grounded in senses; fall back to a template.
    outline = _model_outline(
        user_text=user_text,
        calendar=cal,
        open_items=open_items,
        diary=ctx.get("diary") or [],
        profile=ctx.get("profile") or "",
        knowledge=ctx.get("knowledge") or [],
    )
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

    from friday.persona import owner_name

    reply = f"Here's a working plan for today, {owner_name()}.\n\n" + "\n\n".join(sections)
    return {"reply": reply, "scrubbed": scrubbed, "plan": data, "calendar_n": len(cal)}


def _model_task_proposals(*, user_text: str, ctx: dict[str, Any]) -> list[str]:
    """Model proposes agenda lines only from provided senses — empty if nothing grounding."""
    if not ctx.get("has_signal"):
        return []
    try:
        from friday.models.local import query_model_text

        open_txt = "; ".join((it.get("text") or "")[:80] for it in (ctx.get("open_items") or [])[:8]) or "(none)"
        cal_txt = "; ".join((ctx.get("calendar") or [])[:8]) or "(none)"
        diary_txt = "; ".join((ctx.get("diary") or [])[:4]) or "(none)"
        know_txt = "; ".join((ctx.get("knowledge") or [])[:4]) or "(none)"
        profile = (ctx.get("profile") or "")[:400] or "(none)"
        from friday.prompts import day_plan_propose_prompt

        prompt = day_plan_propose_prompt(
            user_text=user_text or "",
            cal_txt=cal_txt,
            open_txt=open_txt,
            diary_txt=diary_txt,
            know_txt=know_txt,
            profile=profile,
        )
        out = query_model_text(
            prompt,
            format_json=False,
            think=False,
            num_predict=160,
            num_ctx=2048,
        )
        text = (out.get("message") or out.get("raw") or "").strip()
        if not text or "unreachable" in text.lower() or re.search(r"^none\b", text.strip(), re.I):
            return []
        lines = []
        for ln in text.splitlines():
            ln = ln.strip(" -•*\t")
            ln = re.sub(r"^\d+[\).:]\s*", "", ln).strip()
            if len(ln) < 3 or re.match(r"(?i)^none\b", ln):
                continue
            # Reject classic hallucination markers when zero calendar/open support
            if not ctx.get("calendar") and not ctx.get("open_items"):
                if re.search(r"\bquarterly|financial report|kpi review\b", ln, re.I):
                    continue
            lines.append(ln[:120])
        return lines[:5]
    except Exception:  # noqa: BLE001
        return []


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


def _model_outline(
    *,
    user_text: str,
    calendar: list[str],
    open_items: list[dict],
    diary: list[str] | None = None,
    profile: str = "",
    knowledge: list[str] | None = None,
) -> str:
    try:
        from friday.models.local import query_model_text

        open_txt = "; ".join((it.get("text") or "")[:80] for it in open_items[:8]) or "(none)"
        cal_txt = "; ".join(calendar[:8]) or "(none)"
        diary_txt = "; ".join((diary or [])[:4]) or "(none)"
        know_txt = "; ".join((knowledge or [])[:4]) or "(none)"
        profile_txt = (profile or "")[:400] or "(none)"
        from friday.prompts import day_outline_prompt

        prompt = day_outline_prompt(
            user_text=user_text,
            cal_txt=cal_txt,
            open_txt=open_txt,
            diary_txt=diary_txt,
            know_txt=know_txt,
            profile_txt=profile_txt,
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
