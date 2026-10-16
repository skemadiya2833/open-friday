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
# Webcam / desk camera (not screen). Checked before observe.
_CAMERA_LOOK = re.compile(
    r"(?:"
    r"^\s*(?:what am i looking at|what('?s| is) on my desk|what('?s| is) in front of me|"
    r"look at (my )?desk|look at me|use the (web)?camera|through the (web)?camera|"
    r"(web)?camera\b.*\?|(can you|could you) (see|look) (at )?(me|my desk|in front))"
    r"|(?:show|open|display)\b.{0,80}\b(?:(?:web)?camera|what (?:you'?re|you are|it'?s) (?:seeing|looking at))"
    r"|\b(?:what|what'?s|whats)\b.{0,60}\b(?:(?:web)?camera|seeing through)\b"
    r"|\blook through\b.{0,40}\b(?:web)?camera\b"
    r")",
    re.I,
)
_QUESTION = re.compile(
    r"^\s*(who|what|when|where|why|how|can you|could you|would you|is there|"
    r"are there|do you)\b.*\?\s*$",
    re.I,
)
_IMPERATIVE = re.compile(
    r"\b(open|launch|start|click|type|write|save|close|delete|install|download|"
    r"create|rename|move|copy|paste|run|execute|press|drag|scroll|"
    r"show|display|put|bring up|pull up)\b",
    re.I,
)
# "Put my system specs / resources / specification on screen" — act (direct tools → HTML).
_SHOW_ON_SCREEN = re.compile(
    r"\b(show|display|put|bring up|pull up|open|list)\b.{"
    r"0,100}\b(on (my |the )?(screen|desktop|monitor|display)|in (a |my )?notepad|"
    r"system specs?|system info(?:rmation)?|system resources?|hardware (?:info|specs?|resources?)|"
    r"pc specs?|computer specs?|my specs?|my specifications?|specifications?|"
    r"resources?.{0,40}on (the )?system)\b|"
    r"\b(system specs?|system info(?:rmation)?|system resources?|hardware (?:info|specs?)|pc specs?|"
    r"computer specs?|device specs?|my specs?|my specifications?|specifications?|"
    r"resources?.{0,40}on (the )?system)\b.{"
    r"0,60}\b(on (my |the )?(screen|desktop)|in notepad|html|browser)\b",
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

    prompt = f"""You are Friday's intent router for a real local Windows assistant.
Do NOT perform the task. ONLY classify so the right skill can act.

MODES:
- talk: opinions, explanations, brainstorming, greetings (no PC control this turn)
- look: user wants to KNOW what is on screen / describe desktop (NO clicking)
- act: user wants the PC to DO something (open apps, files, shell/git/install, click, type, save, fix, send, create on desktop). Terminal/shell work is still act — the skill prefers PowerShell before mouse.
- remember: store or recall durable personal notes
- research: look something up on the web
- files: read/write files in the workspace
- schedule: reminders, timed tasks, OR today's agenda / "we'll be doing X today"
- clarify: missing detail blocks the next move (which target, when, confirm risk) — ask one short question

AVAILABLE SKILLS:
{_skill_catalog()}

RULES:
- Prefer capability: if they want something DONE on the machine, choose act (or research/files/schedule as appropriate) — not talk.
- Imperatives (open, launch, click, type, write, save, send, fix, install, create on desktop, git, run in terminal/powershell) → act
- Shell-shaped asks (list files, git status, winget, processes, disk space) → act (computer_use will try PowerShell first)
- Questions about seeing/describing the screen only → look (never act)
- "Can you see…" / "what's on my desktop" with no ask to change anything → look
- If unsure between look and act → look
- If unsure between talk and act but there is a clear imperative → act
- Use clarify when guessing would likely do the wrong thing; put the question in objective (one sentence)

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

    # 1) Webcam look-questions → camera skill (never Act).
    # show/open/display with camera still = look, not desktop Act.
    if _CAMERA_LOOK.search(msg):
        return Intent(
            mode="look",
            skill_id="camera",
            confidence=max(intent.confidence, 0.9),
            objective=msg,
            reason=f"policy: camera-look utterance (was {intent.mode}/{intent.skill_id})",
            needs_confirmation=False,
            source="policy",
            raw=intent.raw,
        )

    # 2) Pure screen look-questions can never become Act.
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

    # 3) Act requires imperative language OR high confidence + imperative objective.
    if intent.mode == "act" or intent.skill_id == "computer_use":
        has_imperative = bool(
            _IMPERATIVE.search(msg)
            or _IMPERATIVE.search(intent.objective)
            or _SHOW_ON_SCREEN.search(msg)
        )
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

    # Webcam / desk camera before screen observe.
    # "show/open the camera" still counts as look (imperative words are OK here).
    if _CAMERA_LOOK.search(msg):
        return Intent(
            mode="look",
            skill_id="camera",
            confidence=0.95,
            objective=msg,
            reason="deterministic: camera-look",
            source="policy",
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

    # "Yes / do that / go ahead" → resolve prior ask and actually run a skill (never chat theater).
    follow = _resolve_confirm_followup(msg, history)
    if follow is not None:
        return follow

    # Study / read articles / learn → research skill with learn metadata (via objective wording).
    if _LEARN.search(msg):
        return Intent(
            mode="research",
            skill_id="research",
            confidence=0.94,
            objective=msg,
            reason="deterministic: learn-from-web",
            source="policy",
        )

    # Reminders / timers — explicit verbs only (not bare "every day" inside planning talk).
    from friday.tasks import reminders as _RM

    if _RM.is_reminder_request(msg) or re.search(
        r"\b(what|which|show|list)\b.{0,25}\b(reminders?|alarms?|scheduled)\b", msg, re.I
    ):
        return Intent(mode="schedule", skill_id="tasks", confidence=0.95, objective=msg,
                      reason="deterministic: reminder", source="policy")
    if history:
        last_a = next((t.get("content") or "" for t in reversed(history) if t.get("role") == "assistant"), "")
        if re.search(r"when should I remind|say something like .in 20 minutes", last_a, re.I):
            # Mic often re-hears Friday's own ask; only continue if the user gave a time.
            echo = bool(re.search(
                r"when should I remind|say something like|sure,? (?:boss|chief)",
                msg, re.I,
            ))
            if not echo and (_RM.parse_when(msg) or _RM.is_reminder_request(msg)):
                return Intent(mode="schedule", skill_id="tasks", confidence=0.93, objective=msg,
                              reason="deterministic: reminder follow-up", source="policy")

    # Plan / organise my day (meta) + concrete agenda phrases → tasks skill.
    if _RM.is_agenda_briefing(msg) or re.search(
        r"\b((help (me )?)?(plan|organise|organize|schedule)\s+(my |the |a )?(day|today|agenda)"
        r"|plan my day|make (me )?(a )?(day )?plan|"
        r"we('?ll| will) be doing|for today|today'?s (plan|agenda|tasks)|"
        r"(note|write|jot|take)\s*(down)?\s+(my\s+)?(tasks?|to-?dos?|agenda)|"
        r"add .{0,40}\b(to )?(my )?(plan|agenda)|what('?s| is) (on )?my (plan|agenda)|"
        r"what('?s| is) the plan)\b",
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

    # Open latest research report on screen.
    if re.search(r"\bopen (the |my )?(research )?report\b", msg, re.I):
        return Intent(
            mode="research",
            skill_id="research",
            confidence=0.95,
            objective=msg,
            reason="deterministic: open report",
            source="policy",
        )

    # Open Google Calendar (must beat the research "google" keyword).
    if re.search(
        r"\b(open|launch|show|bring up|pull up)\b.{0,40}\b(google\s+)?calendar\b",
        msg,
        re.I,
    ):
        return Intent(
            mode="act",
            skill_id="computer_use",
            confidence=0.96,
            objective=msg,
            reason="deterministic: open calendar",
            source="policy",
        )

    # Local memory recall — must beat bare "search …" which used to fall into web research.
    if re.search(
        r"\b((search|check|scan|look( in)?|dig)\b.{0,40}\b(your |my |the )?(memory|memories|notes)\b|"
        r"what do you (remember|know|have (on|about))|"
        r"(search|check) (up )?your memory|"
        r"did I (ever )?(tell|mention)|what did I (tell|say) you)\b",
        msg,
        re.I,
    ):
        return Intent(
            mode="remember",
            skill_id="memory",
            confidence=0.94,
            objective=msg,
            reason="deterministic: memory recall",
            source="policy",
        )

    # Web lookup (news, google, "what's the weather") is research — not desktop control.
    # Do not treat "open google calendar/maps/…" as a search.
    # Bare "search" alone is NOT enough (that caught "search your memory").
    if (
        _RESEARCH.search(msg)
        and not _DESKTOP_TARGET.search(msg)
        and not re.search(r"\b(open|launch|show)\b.{0,40}\bgoogle\s+(calendar|maps|drive|docs|mail|meet)\b", msg, re.I)
    ):
        return Intent(
            mode="research",
            skill_id="research",
            confidence=0.93,
            objective=msg,
            reason="deterministic: web lookup",
            source="policy",
        )

    # Device / peripheral inventory → computer_use (direct PowerShell + camera probe, not chat invent).
    if re.search(
        r"\b(?:list|show|scan|enumerate|inventory|what|which|how many)\b.{"
        r"0,80}\b(?:peripherals?|devices?|usb|cameras?|webcams?|web\s*cams?|"
        r"displays?|monitors?|audio|microphones?|printers?|connected (?:devices?|hardware))\b|"
        r"\b(?:device|peripheral|hardware)\s+(?:list|inventory)\b",
        msg,
        re.I,
    ):
        return Intent(
            mode="act",
            skill_id="computer_use",
            confidence=0.94,
            objective=msg,
            reason="deterministic: peripherals inventory",
            source="policy",
        )

    # Week / task dashboard as HTML — tools-first, never mouse agent.
    if re.search(
        r"\b((?:create|make|build|show|display|open|generate)\b.{0,80}\b"
        r"(?:dashboard|board|overview|visual)\b.{0,80}\b(?:week|weekly|tasks?|agenda|plan)|"
        r"(?:week|weekly)\b.{0,60}\b(?:dashboard|overview|board|visual)|"
        r"dashboard\b.{0,60}\b(?:week|weekly|tasks?|agenda)|"
        r"tasks?\b.{0,40}\b(?:for the week|this week|week).{0,40}\b(?:visual|html|dashboard|screen|display))\b",
        msg,
        re.I,
    ):
        return Intent(
            mode="act",
            skill_id="computer_use",
            confidence=0.95,
            objective=msg,
            reason="deterministic: week dashboard html",
            source="policy",
        )

    # Write / generate HTML page → tools-first (write file + open browser), never vision agent.
    if re.search(
        r"\b((?:write|create|make|build|generate|code|draft)\b.{0,100}\bhtml(?:5)?\b|"
        r"html(?:5)?\b.{0,80}\b(?:page|file|document|site|webpage|landing)|"
        r"(?:write|create|make|build|generate)\b.{0,60}\b(?:web\s*page|webpage|landing\s*page))\b",
        msg,
        re.I,
    ):
        return Intent(
            mode="act",
            skill_id="computer_use",
            confidence=0.96,
            objective=msg,
            reason="deterministic: make html page",
            source="policy",
        )

    # Put/show specs/resources on screen → computer_use (tools-first HTML/PowerShell, not vision).
    if _SHOW_ON_SCREEN.search(msg) or (
        re.search(
            r"\b(system specs?|system info(?:rmation)?|system resources?|hardware (?:info|specs?|resources?)|"
            r"pc specs?|resources?.{0,40}on (the )?system)\b",
            msg,
            re.I,
        )
        and re.search(r"\b(screen|desktop|notepad|display|monitor|html|browser|show|list|bring)\b", msg, re.I)
    ):
        return Intent(
            mode="act",
            skill_id="computer_use",
            confidence=0.94,
            objective=msg,
            reason="deterministic: show on screen",
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
    r"\b(search (the web|google|online)|google\b|look ?up|research|find out|"
    r"what('?s| is) (the |today'?s )?(news|weather)|how('?s| is) the weather|"
    r"headlines|breaking news|latest news|weather (today|now|in)|who won|"
    r"(design|ui|ux|visual)\s+(references?|inspiration|examples?|mood ?boards?)|"
    r"(bring|get|find|show|pull up|fetch)\b.{0,60}\b(references?|inspiration|examples?|samples?|mood ?boards?)|"
    r"(references?|inspiration|examples?|mood ?boards?)\b.{0,40}\b(for|of|about)\b|"
    r"business(?:es)?\s+like|"
    r"e-?commerce\s+platforms?|"
    r"platforms?\s+for\b)",
    re.I,
)
_LEARN = re.compile(
    r"\b("
    r"learn (from|about|how)|study (how|about)|read (up )?(on|about)|"
    r"read articles|absorb|internalize|"
    r"teach yourself|research and (learn|remember|memorize)|"
    r"remember (this|these|how|what).{0,40}\b(for next time|going forward)"
    r")\b",
    re.I,
)
_CONFIRM_DO = re.compile(
    r"^\s*("
    r"yes|yeah|yep|yup|sure|ok|okay|alright|all right|"
    r"do (it|that)|go ahead|please do|just do (it|that)|"
    r"do that for me|(you|he|she) (has|have|must|should|need) to do|"
    r"put (them|it|that) on (my |the )?screen|"
    r"i prefer .{0,60}on (my |the )?screen"
    r")\b",
    re.I,
)


def _last_substantive_user(history: list[dict[str, str]] | None) -> str:
    if not history:
        return ""
    for turn in reversed(history):
        if turn.get("role") != "user":
            continue
        text = (turn.get("content") or "").strip()
        if not text or _CONFIRM_DO.search(text):
            continue
        if len(text) < 4:
            continue
        return text
    return ""


def _resolve_confirm_followup(
    msg: str, history: list[dict[str, str]] | None
) -> Intent | None:
    """Map short confirmations onto the prior real ask so we act instead of chatting."""
    if not _CONFIRM_DO.search(msg):
        return None
    prior = _last_substantive_user(history)
    last_a = ""
    if history:
        last_a = next(
            (t.get("content") or "" for t in reversed(history) if t.get("role") == "assistant"),
            "",
        )
    # Prefer prior user topic; fall back to what the assistant offered to do.
    objective = prior
    if not objective and last_a:
        m = re.search(
            r"(?:shall i|i can|let me|want me to)\s+(.{12,160}?)(?:\?|$)",
            last_a,
            re.I,
        )
        if m:
            objective = m.group(1).strip()
    if not objective:
        return None
    blob = f"{msg} {objective} {last_a}".lower()
    if _LEARN.search(objective) or _LEARN.search(last_a):
        return Intent(
            mode="research",
            skill_id="research",
            confidence=0.93,
            objective=objective,
            reason="deterministic: confirm→learn",
            source="policy",
        )
    if (
        _RESEARCH.search(objective)
        or re.search(r"\b(reference|website|search|browser|sites?)\b", blob, re.I)
    ):
        return Intent(
            mode="research",
            skill_id="research",
            confidence=0.93,
            objective=objective,
            reason="deterministic: confirm→research",
            source="policy",
        )
    if _IMPERATIVE.search(objective) or re.search(
        r"\b(screen|desktop|chrome|notepad|open|click|type)\b", blob, re.I
    ):
        return Intent(
            mode="act",
            skill_id="computer_use",
            confidence=0.92,
            objective=objective,
            reason="deterministic: confirm→act",
            source="policy",
        )
    # Default: treat confirmation of a prior topic as research (look it up for real).
    return Intent(
        mode="research",
        skill_id="research",
        confidence=0.9,
        objective=objective,
        reason="deterministic: confirm→research-default",
        source="policy",
    )
_DESKTOP_TARGET = re.compile(
    r"\b(notepad|chrome|edge|firefox|browser window|desktop|click|type in|"
    r"calendar|google calendar|"
    r"open (the )?(chrome|browser|edge|notepad|calendar))\b",
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
