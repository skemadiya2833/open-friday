"""
Intent brain — architectural gate before any skill runs.

LLM proposes mode/skill; a deterministic policy layer validates and can
downgrade dangerous mistakes (e.g. "what's on my screen?" → never Act).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from friday.skills.registry import get_registry

Mode = Literal["talk", "look", "act", "remember", "research", "files", "schedule", "clarify"]

_MODE_TO_SKILL = {
    "talk": "chat",
    "look": "observe",
    "act": "computer_use",
    "remember": "memory",
    "research": "research",
    "files": "files",
    "schedule": "tasks",
    "clarify": "chat",
}

# Deterministic vetoes — these override a confused model.
_LOOK_ONLY = re.compile(
    r"^\s*(can you see|do you see|what (do you )?see|what('?s| is) (going )?on|"
    r"what('?s| is) on (my |the )?(screen|desktop|monitor|display)|"
    r"describe (my |the )?(screen|desktop|display)|look at (my )?(screen|desktop)|"
    r"tell me what you see|is (my )?(screen|desktop))\b",
    re.I,
)
_QUESTION = re.compile(
    r"^\s*(who|what|when|where|why|how|can you|could you|would you|is there|"
    r"are there|do you)\b.*\?\s*$",
    re.I,
)
_IMPERATIVE = re.compile(
    r"\b(open|launch|start|click|type|write|save|close|delete|install|download|"
    r"create|rename|move|copy|paste|run|execute|press|drag|scroll)\b",
    re.I,
)


@dataclass
class Intent:
    mode: Mode
    skill_id: str
    confidence: float
    objective: str
    reason: str
    needs_confirmation: bool = False
    source: str = "classifier"  # classifier | policy | override | fallback
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "skill_id": self.skill_id,
            "confidence": self.confidence,
            "objective": self.objective,
            "reason": self.reason,
            "needs_confirmation": self.needs_confirmation,
            "source": self.source,
        }


def _skill_catalog() -> str:
    lines = []
    for m in get_registry().list():
        if not m.enabled:
            continue
        lines.append(f"- {m.id}: {m.description}")
    return "\n".join(lines) or "- chat: general conversation"


def _parse_intent_json(text: str) -> dict[str, Any] | None:
    text = text.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return None
    return None


def _llm_classify(message: str, history: list[dict[str, str]] | None = None) -> dict[str, Any] | None:
    from friday.config import CHAT_NUM_CTX
    from friday.models.local import query_model_text

    hist = ""
    for turn in (history or [])[-4:]:
        hist += f"{turn.get('role', 'user')}: {(turn.get('content') or '')[:200]}\n"

    prompt = f"""You are Friday's intent classifier. Choose ONE mode for the user message.
Do NOT perform the task. ONLY classify.

MODES:
- talk: chat, opinions, explanations, greetings (no screen control)
- look: user wants to KNOW what is on screen / describe desktop (NO clicking)
- act: user wants you to CONTROL the PC (open apps, click, type, save) — imperative only
- remember: store or recall personal notes in memory
- research: look something up on the web
- files: read/write files in the workspace
- schedule: reminders, timed tasks, OR today's agenda / "we'll be doing X today"
- clarify: message is ambiguous — ask a short clarifying question instead of acting

AVAILABLE SKILLS:
{_skill_catalog()}

RULES:
- Questions about seeing/describing the screen → look (never act)
- "Can you see…" / "what's going on on my desktop" → look
- Only act if the user clearly wants an action performed on their computer
- If unsure between look and act → look
- If unsure between talk and act → talk or clarify

Recent conversation:
{hist or "(none)"}

User message:
{message}

Reply with ONLY JSON (no markdown):
{{"mode":"look","skill_id":"observe","confidence":0.0,"objective":"short rewritten goal","reason":"one clause","needs_confirmation":false}}
"""
    result = query_model_text(
        prompt,
        format_json=False,
        reasoning_mode=False,
        num_predict=180,
        num_ctx=min(2048, CHAT_NUM_CTX),
    )
    raw = (result.get("message") or result.get("raw") or "").strip()
    return _parse_intent_json(raw)


def _normalize_proposed(data: dict[str, Any], message: str) -> Intent:
    mode = str(data.get("mode") or "talk").lower().strip()
    if mode not in _MODE_TO_SKILL:
        mode = "talk"
    skill = str(data.get("skill_id") or _MODE_TO_SKILL[mode]).lower().strip()
    # Force skill to match mode when mismatched
    expected = _MODE_TO_SKILL[mode]
    if skill not in {m.id for m in get_registry().list()}:
        skill = expected
    if mode == "act" and skill != "computer_use":
        skill = "computer_use"
    if mode == "look" and skill != "observe":
        skill = "observe"
    try:
        conf = float(data.get("confidence") or 0.5)
    except (TypeError, ValueError):
        conf = 0.5
    conf = max(0.0, min(1.0, conf))
    objective = str(data.get("objective") or message).strip() or message
    reason = str(data.get("reason") or "classified").strip()
    needs = bool(data.get("needs_confirmation"))
    return Intent(
        mode=mode,  # type: ignore[arg-type]
        skill_id=skill,
        confidence=conf,
        objective=objective,
        reason=reason,
        needs_confirmation=needs,
        source="classifier",
        raw=data,
    )


def apply_policy(intent: Intent, message: str) -> Intent:
    """
    Deterministic safety rail. The model proposes; policy may veto Act.
    This is what prevents dumb mistakes architecturally.
    """
    msg = message.strip()

    # 1) Pure look-questions can never become Act.
    if _LOOK_ONLY.search(msg) and not _IMPERATIVE.search(msg):
        return Intent(
            mode="look",
            skill_id="observe",
            confidence=max(intent.confidence, 0.9),
            objective=msg,
            reason=f"policy: look-only utterance (was {intent.mode}/{intent.skill_id})",
            needs_confirmation=False,
            source="policy",
            raw=intent.raw,
        )

    # 2) Act requires imperative language OR high confidence + imperative objective.
    if intent.mode == "act" or intent.skill_id == "computer_use":
        has_imperative = bool(_IMPERATIVE.search(msg) or _IMPERATIVE.search(intent.objective))
        if not has_imperative:
            # Downgrade: question without action verbs → look if screen-related else talk
            if re.search(r"\b(screen|desktop|monitor|display|window|open apps?)\b", msg, re.I):
                return Intent(
                    mode="look",
                    skill_id="observe",
                    confidence=0.85,
                    objective=msg,
                    reason="policy: vetoed act — no imperative verbs",
                    source="policy",
                    raw=intent.raw,
                )
            return Intent(
                mode="talk",
                skill_id="chat",
                confidence=0.8,
                objective=msg,
                reason="policy: vetoed act — conversational, not a PC task",
                source="policy",
                raw=intent.raw,
            )
        if intent.confidence < 0.55:
            intent.needs_confirmation = True
            intent.reason += "; policy: low confidence act"
            intent.source = "policy"

    # 3) Bare questions without imperatives should not act.
    if _QUESTION.search(msg) and not _IMPERATIVE.search(msg):
        if intent.mode == "act":
            return Intent(
                mode="talk",
                skill_id="chat",
                confidence=0.75,
                objective=msg,
                reason="policy: vetoed act on interrogative",
                source="policy",
                raw=intent.raw,
            )

    # Ensure skill exists / enabled
    skill = get_registry().get(intent.skill_id)
    if skill is None or not skill.manifest.enabled:
        intent.skill_id = _MODE_TO_SKILL.get(intent.mode, "chat")
        intent.reason += "; policy: skill missing → remapped"
        intent.source = "policy"

    return intent


def _deterministic_intent(message: str, history: list[dict[str, str]] | None = None) -> Intent | None:
    """
    Decide without the LLM when the utterance is unambiguous.
    This is the architectural fix: never ask a confused model a solved question.
    """
    msg = message.strip()
    if not msg:
        return Intent(
            mode="talk", skill_id="chat", confidence=1.0,
            objective=msg, reason="empty", source="policy",
        )

    # Look-only questions → observe. No LLM vote.
    if _LOOK_ONLY.search(msg) and not _IMPERATIVE.search(msg):
        return Intent(
            mode="look",
            skill_id="observe",
            confidence=0.95,
            objective=msg,
            reason="deterministic: look-only",
            source="policy",
        )

# Short greets / pure chat without tools.
    if re.match(
        r"^(hi|hello|hey|thanks|thank you|good (morning|afternoon|evening)|"
        r"how are you|what('?s| is) your name)\b[!?.]*$",
        msg,
        re.I,
    ):
        return Intent(
            mode="talk",
            skill_id="chat",
            confidence=0.95,
            objective=msg,
            reason="deterministic: greeting",
            source="policy",
        )

    # Reminders / timers / recurring tasks: parsed locally and scheduled without asking.
    from friday.tasks.reminders import INTENT as _REMIND

    if _REMIND.search(msg) or re.search(r"\b(what|which|show|list)\b.{0,25}\b(reminders?|alarms?|scheduled)\b", msg, re.I):
        return Intent(mode="schedule", skill_id="tasks", confidence=0.95, objective=msg,
                      reason="deterministic: reminder", source="policy")
    if history:
        last_a = next((t.get("content") or "" for t in reversed(history) if t.get("role") == "assistant"), "")
        if re.search(r"when should I remind|say something like .in 20 minutes", last_a, re.I):
            return Intent(mode="schedule", skill_id="tasks", confidence=0.93, objective=msg,
                          reason="deterministic: reminder follow-up", source="policy")

    # Today's agenda phrases → tasks skill without waiting on the classifier.
    if re.search(
        r"\b(we('?ll| will) be doing|for today|today'?s (plan|agenda)|"
        r"add .{0,40}\b(to )?(my )?(plan|agenda)|what('?s| is) (on )?my (plan|agenda))\b",
        msg,
        re.I,
    ):
        return Intent(
            mode="schedule",
            skill_id="tasks",
            confidence=0.92,
            objective=msg,
            reason="deterministic: today agenda",
            source="policy",
        )

    # Web lookup (news, google, "what's the weather") is research — not desktop control.
    if _RESEARCH.search(msg) and not _DESKTOP_TARGET.search(msg):
        return Intent(
            mode="research",
            skill_id="research",
            confidence=0.93,
            objective=msg,
            reason="deterministic: web lookup",
            source="policy",
        )

    # Clear imperative desktop task → act. Still runs through apply_policy.
    if _IMPERATIVE.search(msg) and re.search(
        r"\b(notepad|chrome|browser|file|folder|window|app|desktop|"
        r"pc|computer|excel|word|discord|spotify|settings)\b",
        msg,
        re.I,
    ):
        return Intent(
            mode="act",
            skill_id="computer_use",
            confidence=0.88,
            objective=msg,
            reason="deterministic: imperative + target",
            source="policy",
        )

    # Plain conversation: nothing here needs a tool, so skip the classifier round-trip (saves seconds per turn).
    if not _NEEDS_LLM.search(msg) and len(msg) < 500:
        return Intent(mode="talk", skill_id="chat", confidence=0.85, objective=msg,
                      reason="deterministic: conversation", source="policy")

    return None


_RESEARCH = re.compile(
    r"\b(search( the web| google| online)?|google\b|look ?up|research|find out|"
    r"what('?s| is) (the |today'?s )?(news|weather)|how('?s| is) the weather|"
    r"headlines|breaking news|latest news|weather (today|now|in)|who won)\b",
    re.I,
)
_DESKTOP_TARGET = re.compile(
    r"\b(notepad|chrome|edge|firefox|browser window|desktop|click|type in|"
    r"open (the )?(chrome|browser|edge|notepad))\b",
    re.I,
)
_NEEDS_LLM = re.compile(
    r"\b(screen|desktop|monitor|display|window|windows|app|apps|open|launch|start|click|type|write|save|close|delete|"
    r"file|files|folder|search|google|look ?up|research|browse|website|find|plan|agenda|task|tasks|memory|forget|download|"
    r"install|run|play|send|email|e-?mail|message|whatsapp|rename|move|copy|paste|scroll|press|drag|"
    r"notepad|chrome|excel|word|discord|spotify|settings|pc|computer)\b",
    re.I,
)


def classify_intent(
    message: str,
    *,
    history: list[dict[str, str]] | None = None,
    override_skill: str | None = None,
) -> Intent:
    """Main entry: deterministic → LLM → policy. Act is never trusted alone."""
    if override_skill:
        mode: Mode = "act" if override_skill == "computer_use" else "talk"
        for m, sid in _MODE_TO_SKILL.items():
            if sid == override_skill:
                mode = m  # type: ignore[assignment]
                break
        proposed = Intent(
            mode=mode,
            skill_id=override_skill,
            confidence=1.0,
            objective=message,
            reason="manual override",
            source="override",
        )
        return apply_policy(proposed, message)

    # 1) Solved cases never reach the LLM.
    proposed = _deterministic_intent(message, history)
    if proposed is None:
        try:
            data = _llm_classify(message, history)
        except Exception as exc:
            print(f"[Intent] classifier failed: {exc}")
            data = None

        if not data:
            # Safe fallback: never act without a successful classify
            proposed = Intent(
                mode="talk",
                skill_id="chat",
                confidence=0.3,
                objective=message,
                reason="fallback: classifier unavailable",
                source="fallback",
            )
        else:
            proposed = _normalize_proposed(data, message)

    # 2) Policy always has the last word (especially vetoing Act).
    final = apply_policy(proposed, message)
    print(
        f"[Intent] {final.mode}/{final.skill_id} "
        f"conf={final.confidence:.2f} src={final.source} — {final.reason}"
    )
    return final
