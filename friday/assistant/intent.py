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

Mode = Literal["talk", "look", "act", "cad", "remember", "research", "files", "schedule", "clarify"]

_MODE_TO_SKILL = {
    "talk": "chat",
    "look": "observe",
    "act": "computer_use",
    "cad": "cad",
    "remember": "memory",
    "research": "research",
    "files": "files",
    "schedule": "tasks",
    "clarify": "chat",
}

# Deterministic vetoes — these override a confused model.
# Optional leading address so "Okay Friday what's on my screen" still looks.
_ADDR = r"(?:(?:hey|hi|hello|okay|ok)\s+)?(?:friday\s*[,:]?\s*)?"
_LOOK_ONLY = re.compile(
    rf"^\s*{_ADDR}("
    r"can you see|do you see|what (do you )?see|"
    r"what('?s| is) going on( here| on (my |the )?(screen|desktop|monitor|display))?|"
    r"what('?s| is) on (my |the )?(screen|desktop|monitor|display)|"
    r"describe (my |the )?(screen|desktop|display)|look at (my )?(screen|desktop)|"
    r"tell me what you see|is (my )?(screen|desktop)"
    r")\b",
    re.I,
)
# Sitrep / "what's going on" with no screen words → chat (agenda/time), not desktop act.
_SITUATION_ASK = re.compile(
    rf"(?i)^\s*{_ADDR}("
    r"what('?s| is) (going on|up)( (today|tonight|this (evening|afternoon|morning)))?|"
    r"what('?s| is) the (status|sitrep|situation)|"
    r"status report|sitrep|"
    r"anything (going )?on|"
    r"how('?s| is) (it|everything) (looking|going)"
    r")\s*[?.!]?\s*$"
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

    from friday.prompts import intent_router_prompt

    prompt = intent_router_prompt(
        message=message,
        hist=hist,
        skill_catalog=_skill_catalog(),
    )
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
    if mode == "cad" and skill != "cad":
        skill = "cad"
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

    # 2) Sitrep without screen words can never become Act / observe.
    if _SITUATION_ASK.match(msg) and not re.search(
        r"\b(screen|desktop|monitor|display)\b", msg, re.I
    ):
        return Intent(
            mode="talk",
            skill_id="chat",
            confidence=max(intent.confidence, 0.9),
            objective=msg,
            reason=f"policy: situation ask (was {intent.mode}/{intent.skill_id})",
            needs_confirmation=False,
            source="policy",
            raw=intent.raw,
        )

    # 3) Pure screen look-questions can never become Act.
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

    # 4) Act requires imperative language OR high confidence + imperative objective.
    if intent.mode == "act" or intent.skill_id == "computer_use":
        # Measuring this PC is a real tool action even when phrased as a question.
        measure_hw = bool(
            "measure hardware" in (intent.reason or "")
            or re.search(
                r"\b(system specs?|hardware (?:status|check|report|info|specs?)|"
                r"system hardware|pc specs?|my (?:system )?specs?)\b",
                msg,
                re.I,
            )
        )
        has_imperative = bool(
            _IMPERATIVE.search(msg)
            or _IMPERATIVE.search(intent.objective)
            or _SHOW_ON_SCREEN.search(msg)
            or measure_hw
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

    # 3) Bare questions without imperatives should not act (except measured hardware).
    if _QUESTION.search(msg) and not _IMPERATIVE.search(msg):
        if intent.mode == "act" and "measure hardware" not in (intent.reason or ""):
            if not re.search(
                r"\b(system specs?|hardware (?:status|check|report)|pc specs?)\b",
                msg,
                re.I,
            ):
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

    # Sitrep / "what's going on" (no screen) → talk — never computer_use.
    if _SITUATION_ASK.match(msg) and not re.search(
        r"\b(screen|desktop|monitor|display)\b", msg, re.I
    ):
        return Intent(
            mode="talk",
            skill_id="chat",
            confidence=0.95,
            objective=msg,
            reason="deterministic: situation",
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

    # "That was thinking — give me the answer" after an optics dump → look again.
    retry_look = _resolve_observe_answer_retry(msg, history)
    if retry_look is not None:
        return retry_look

    # Short greets / pure chat without tools (includes "Hey Friday").
    from friday.assistant.reflexes import _is_greeting_only

    if _is_greeting_only(msg) or re.match(
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

    # After "what should I search?" → this turn is the topic (run research, don't chat).
    topic_follow = _resolve_research_topic_reply(msg, history)
    if topic_follow is not None:
        return topic_follow

    # "Did you pull up / find those … ideas?" → research (open findings or look up), not glitchy chat.
    prior_research = _resolve_prior_research_ask(msg, history)
    if prior_research is not None:
        return prior_research

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
        r"what('?s| is) (up for )?today|what('?s| is) the plan( for today)?|"
        r"(tell me |read )?(the |my )?plan for today|agenda for today)\b",
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

    # Conversational CAD: "make a 3d model…", plates/brackets with sizes, FreeCAD/Taiga.
    # Before HTML "build a page" / research. Skip filament / slicer shopping.
    # Also catch short solids ("make a cube") — otherwise chat invents .FCStd / desktop saves.
    if (
        re.search(
            # ASR: "free CID" / "free cad" → FreeCAD
            r"\b(freecad|free\s*c(?:ad|id)|free\s*cad|freecid|taiga(?:-s1)?|biome-s1|\.?fcstd)\b|"
            r"\b(?:set\s*up|setup|enable|disable|launch|start)\b.{0,40}\b(?:cad|freecad|taiga)\b|"
            r"\b(?:cad|freecad|taiga|free\s*c(?:ad|id))\b.{0,40}\b"
            r"(?:set\s*up|setup|status|enable|disable|launch|open(?:ed)?|server)\b|"
            r"\b(?:3\s*-?\s*d|3d|cad)\s*(?:model|part|solid|object|file)\b|"
            r"\b(?:make|build|model|design|sketch|create|save)\b.{0,40}\b(?:a\s+)?(?:3\s*-?\s*d|3d)\s*(?:model|part|file)?\b|"
            r"\b(?:how about|let'?s|can we|could we|we (?:should|could)|i want)\b.{0,80}\b"
            r"(?:3\s*-?\s*d|3d|cad|model|plate|bracket|flange|part|cube|box|sphere)\b|"
            r"\b(?:build|make|model|design|sketch|create|save)\b.{0,80}\b(?:in\s+)?freecad\b|"
            r"\b(?:cad|partdesign|part\s*design)\b.{0,60}\b(?:part|plate|bracket|flange|model)\b|"
            r"\b(?:build|make|model|design|create)\b.{0,80}\b"
            r"(?:plate|bracket|flange|boss|pocket|cylinder|hex(?:agon)?|cube|box|sphere|solid)\b|"
            r"\b(?:make|build|create|model)\b.{0,40}\b(?:a\s+)?(?:cube|box|sphere|cylinder)\b|"
            r"\b(?:save|put|drop|create)\b.{0,60}\b(?:fcstd|\.fcstd|freecad|3\s*-?\s*d|cad)\b.{0,40}\b"
            r"(?:desktop|download)\b|"
            r"\b(?:fcstd|\.fcstd|freecad|3\s*-?\s*d\s*model|cad\s*(?:file|part))\b.{0,40}\b"
            r"(?:on\s+(?:my\s+)?desktop|to\s+(?:my\s+)?desktop)\b|"
            r"\b\d+(?:\.\d+)?\s*[x×]\s*\d+(?:\.\d+)?\s*[x×]\s*\d+(?:\.\d+)?\b.{0,40}\b"
            r"(?:plate|box|block|bracket|mm|fillet|hole)\b|"
            r"\b(?:plate|bracket|flange)\b.{0,60}\b(?:mm|fillet|hole|chamfer|polar)\b|"
            r"[A-Za-z]:\\[^\n]{0,80}FreeCAD",
            msg,
            re.I,
        )
        and not re.search(
            r"\b(filament|3d\s*print|printer|slicer|gcode|html(?:5)?|web\s*page|webpage|landing\s*page)\b",
            msg,
            re.I,
        )
    ):
        return Intent(
            mode="cad",
            skill_id="cad",
            confidence=0.95,
            objective=msg,
            reason="deterministic: conversational cad / freecad",
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

    # Vague "do a search / look something up" with no topic → ask once, then research.
    if _is_vague_research_ask(msg):
        return Intent(
            mode="clarify",
            skill_id="chat",
            confidence=0.96,
            objective="What should I search for — give me a topic or question.",
            reason="deterministic: vague research → clarify topic",
            source="policy",
        )

    # Project continuity / brainstorm with the owner — chat + memory, NOT a web crawl.
    if re.search(
        r"(?i)\b("
        r"continue (on |with )?(our |the |my )?|"
        r"other tasks? (we|i) could|"
        r"what else (can|should|could) we|"
        r"what (can|should|could) we (do|work on)|"
        r"brainstorm|"
        r"our (robot|esp|taskbot|project|setup)|"
        r"how (can|do) (i|we) get .{0,40} setup|"
        r"finish (the |our )?setup|"
        r"pick up where we left"
        r")\b",
        msg,
    ):
        return Intent(
            mode="talk",
            skill_id="chat",
            confidence=0.92,
            objective=msg,
            reason="deterministic: project continuity / brainstorm",
            source="policy",
        )

    # Web lookup (news, google, "what's the weather") is research — not desktop control.
    # Do not treat "open google calendar/maps/…" as a search.
    # Bare "search" alone is NOT enough (that caught "search your memory").
    if (
        (_RESEARCH.search(msg) or _SEARCH_VERB.search(msg))
        and not _DESKTOP_TARGET.search(msg)
        and not re.search(r"\b(open|launch|show)\b.{0,40}\bgoogle\s+(calendar|maps|drive|docs|mail|meet)\b", msg, re.I)
        and not re.search(r"\b(your |my )?memory\b", msg, re.I)
        and not re.search(r"(?i)\b(tell me (some |an? )?(other )?tasks?|continue on our)\b", msg)
    ):
        if not _research_topic_residue(msg):
            return Intent(
                mode="clarify",
                skill_id="chat",
                confidence=0.95,
                objective="What should I search for — give me a topic or question.",
                reason="deterministic: research missing topic",
                source="policy",
            )
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

    # Hardware / specs — always measure via PowerShell (never let chat invent a 4090).
    if re.search(
        r"\b("
        r"system specs?|system info(?:rmation)?|system resources?|"
        r"hardware (?:info|specs?|resources?|status|check|report|summary)|"
        r"system hardware|current hardware|(?:my )?hardware status|"
        r"pc specs?|computer specs?|my specs?|"
        r"resources?.{0,40}on (the )?system|"
        r"(?:where(?:'s| is)|what(?:'s| is)|check|show|list|get)\b.{0,50}\b"
        r"(?:hardware|system specs?|pc specs?|gpu|vram|ram)\b"
        r")\b",
        msg,
        re.I,
    ):
        return Intent(
            mode="act",
            skill_id="computer_use",
            confidence=0.96,
            objective=msg,
            reason="deterministic: measure hardware",
            source="policy",
        )

    # "Put them / the ones you searched on screen" after research → open findings.
    show_findings = _resolve_show_research_findings(msg, history)
    if show_findings is not None:
        return show_findings

    # Put/show other content on screen → computer_use (tools-first, not vision).
    if _SHOW_ON_SCREEN.search(msg):
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
# Broader search verb (needs a topic residue — otherwise clarify).
_SEARCH_VERB = re.compile(
    r"\b("
    r"search|searches|searching|look\s*ups?|looking\s+up|"
    r"look\s+(?:\w+\s+){0,3}up|"
    r"research(?:ing|es)?|google|"
    r"do\s+(?:a\s+|me\s+a\s+)?(?:little\s+|quick\s+|small\s+|fast\s+)?(?:web\s+|online\s+)?search"
    r")\b",
    re.I,
)
_VAGUE_SEARCH_ASK = re.compile(
    r"(?i)^\s*(?:(?:hey|hi|okay|ok)\s+)?(?:friday[,:]?\s*)?"
    r"(?:(?:can|could|would|will)\s+you\s+)?"
    r"(?:please\s+)?"
    r"(?:"
    r"(?:do|run|perform)\s+(?:a\s+|me\s+a\s+)?(?:little\s+|quick\s+|small\s+|fast\s+)?"
    r"(?:web\s+|google\s+|online\s+)?(?:search|lookup|research)\b|"
    r"(?:search|look\s*up|research|google)\s*(?:(?:the\s+)?(?:web|internet|online))?\s*"
    r"(?:for\s+me|something|stuff|things?)?\b|"
    r"(?:search|look\s*up|research)\s+(?:something|stuff|things?)\b|"
    r"look\s+(?:something|stuff|things?)\s+up\b"
    r")"
    r"(?:\s+for\s+me)?(?:\s+please)?(?:\s+real\s+quick)?\s*[.?!]*\s*$"
)
_ASKED_RESEARCH_TOPIC = re.compile(
    r"(?i)\b("
    r"what should i search|"
    r"what (?:do you want|should i|shall i) (?:me to )?(?:search|look up|research|google)|"
    r"what topic|"
    r"give me a topic|"
    r"search for —|"
    r"what (?:are we|am i) (?:looking|searching) up"
    r")\b"
)


def _research_topic_residue(msg: str) -> str:
    """Strip search scaffolding; leftover is the real topic (empty → ask)."""
    t = re.sub(
        r"(?i)\b("
        r"please|hey|hi|ok|okay|friday|boss|"
        r"can you|could you|would you|will you|"
        r"do (?:a |me a )?(?:little |quick |small |fast )?(?:web |google |online )?(?:search|lookup|research)|"
        r"search(?:es|ing)?(?: the web| google| online| for me)?|"
        r"look(?:ing)?\s*ups?|research(?:ing|es)?|google|find out|"
        r"for me|real quick|quickly|something|stuff|things?|a bit|a little|"
        r"the web|online|internet|about|regarding|concerning"
        r")\b",
        " ",
        msg or "",
    )
    t = re.sub(r"(?i)^\s*(for|on|of|to)\s+", "", t)
    t = re.sub(r"\s+", " ", t).strip(" .?!,;:\"'")
    # Need a real noun/phrase — not just "it" / "that".
    if len(t) < 3 or t.lower() in {"it", "that", "this", "them", "those", "one", "about"}:
        return ""
    return t


def _is_vague_research_ask(msg: str) -> bool:
    if _VAGUE_SEARCH_ASK.match(msg or ""):
        return True
    if (_RESEARCH.search(msg or "") or _SEARCH_VERB.search(msg or "")) and not _research_topic_residue(msg):
        # "search your memory" is memory, not vague web.
        if re.search(r"(?i)\b(your |my )?memory\b", msg or ""):
            return False
        return True
    return False


def _resolve_research_topic_reply(
    msg: str, history: list[dict[str, str]] | None
) -> Intent | None:
    """If Friday just asked for a search topic, treat this utterance as that topic."""
    if not history or not (msg or "").strip():
        return None
    last_a = next(
        (t.get("content") or "" for t in reversed(history) if t.get("role") == "assistant"),
        "",
    )
    if not _ASKED_RESEARCH_TOPIC.search(last_a):
        return None
    if _LOOK_ONLY.search(msg) or _CAMERA_LOOK.search(msg):
        return None
    if re.search(r"(?i)\b(never ?mind|cancel|forget it|stop)\b", msg):
        return Intent(
            mode="talk",
            skill_id="chat",
            confidence=0.9,
            objective=msg,
            reason="deterministic: research topic cancelled",
            source="policy",
        )
    topic = _research_topic_residue(msg) or msg.strip()
    if len(topic) < 2:
        return None
    return Intent(
        mode="research",
        skill_id="research",
        confidence=0.95,
        objective=topic,
        reason="deterministic: research-topic-reply",
        source="policy",
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
# Short confirms only — whole utterance. "yeah do that research" must NOT match
# (that is handled by _CONFIRM_RESEARCH or web lookup with a real topic).
_CONFIRM_DO = re.compile(
    r"^\s*(?:"
    r"(?:yes|yeah|yep|yup|sure|ok|okay|alright|all right)"
    r"(?:\s+(?:please|do (?:it|that)|go ahead|just do (?:it|that)|do that for me))*|"
    r"do (?:it|that)|go ahead|please do|just do (?:it|that)|do that for me|"
    r"(?:you|he|she) (?:has|have|must|should|need) to do|"
    r"put (?:them|it|that) on (?:my |the )?screen|"
    r"i prefer .{0,60}on (?:my |the )?screen"
    r")"
    r"(?:\s+(?:please|thanks|thank you|for me|now|then|boss)){0,3}"
    r"(?:\s*[.\!\,]*)?\s*$",
    re.I,
)
# "do that research" / "yeah run the research" — confirm an offered lookup, not a new topic.
_CONFIRM_RESEARCH = re.compile(
    r"(?i)^\s*(?:(?:yes|yeah|yep|yup|sure|ok|okay)\s+)?"
    r"(?:please\s+)?"
    r"(?:do|run|start|begin)\s+(?:that|the|this|my)\s+"
    r"(?:little\s+|quick\s+)?research\b"
    r"(?:\s+for\s+me)?(?:\s+please)?(?:\s*[.\!\,]*)?\s*$"
)


_SHOW_RESEARCH_REF = re.compile(
    r"(?i)\b("
    r"(?:put|show|display|bring up|pull up|open)\b.{0,80}\b"
    r"(?:them|those|that|it|the (?:results?|findings?|research|links?|sources?|hits?))\b"
    r".{0,50}\b(?:on (?:my |the )?(?:screen|desktop|monitor)|in (?:a |my )?notepad|"
    r"in (?:the )?browser)|"
    r"(?:the )?(?:ones?|results?|findings?|links?|sources?|hits?)\s+"
    r"(?:you\s+)?(?:searched|found|looked\s*up|researched|got|pulled)|"
    r"put\s+(?:the\s+)?(?:research|results?|findings?)\s+on\s+(?:my\s+|the\s+)?screen"
    r")\b"
)


def _last_assistant_looks_like_research(history: list[dict[str, str]] | None) -> bool:
    if not history:
        return False
    for turn in reversed(history):
        if turn.get("role") != "assistant":
            continue
        text = turn.get("content") or ""
        return bool(
            re.search(
                r"(?i)\b("
                r"search results|top hits|gathered|looked up|from the (web|results)|"
                r"here(?:'s| is) what I found|i(?:'ve| have) found|"
                r"sources?|research on|initial research"
                r")\b",
                text,
            )
        )
    return False


def _last_user_was_research_ask(history: list[dict[str, str]] | None) -> bool:
    prior = _last_substantive_user(history)
    if not prior:
        return False
    return bool(_RESEARCH.search(prior) or _SEARCH_VERB.search(prior))


_PRIOR_RESEARCH_ASK = re.compile(
    r"(?i)\b("
    r"did you (pull up|look up|search|find|research|get)|"
    r"have you (pulled up|looked up|searched|found|researched)|"
    r"where (are|is) (the |those |that )?(results?|findings?|ideas?|links?|research)|"
    r"what (did you|about the) (find|research|search)|"
    r"(show|open|bring up|pull up)\b.{0,40}\b(ideas?|findings?|results?|research)\b"
    r")\b"
)


def _resolve_prior_research_ask(
    msg: str, history: list[dict[str, str]] | None
) -> Intent | None:
    """Map 'did you pull up those 3D printing ideas' onto research, not chat theater."""
    if not _PRIOR_RESEARCH_ASK.search(msg):
        return None
    # Prefer opening last findings when history/context says research already ran.
    if _last_assistant_looks_like_research(history) or _last_user_was_research_ask(history):
        return Intent(
            mode="research",
            skill_id="research",
            confidence=0.93,
            objective="open research findings on screen",
            reason="deterministic: prior research follow-up → show findings",
            source="policy",
        )
    # Otherwise treat the utterance as a fresh research ask (strip the "did you" wrapper).
    topic = re.sub(
        r"(?i)^\s*(did you|have you|can you|could you)\s+"
        r"(pull up|look up|search|find|research|get)\s+",
        "",
        msg,
    ).strip()
    topic = re.sub(r"(?i)\b(those|the|that|uh+|like|and)\b", " ", topic)
    topic = re.sub(r"\s+", " ", topic).strip(" .?!,") or msg
    return Intent(
        mode="research",
        skill_id="research",
        confidence=0.9,
        objective=topic,
        reason="deterministic: prior-research ask → look up",
        source="policy",
    )


def _resolve_show_research_findings(
    msg: str, history: list[dict[str, str]] | None
) -> Intent | None:
    """Map 'put them on screen' / 'the ones you searched' onto opening last findings."""
    names_results = bool(_SHOW_RESEARCH_REF.search(msg))
    pronoun_on_screen = bool(
        _SHOW_ON_SCREEN.search(msg)
        and re.search(
            r"(?i)\b(them|those|that|it|results?|findings?|research|ones?|hits?)\b",
            msg,
        )
    )
    if not names_results and not pronoun_on_screen:
        return None
    # Wording that names search results is enough; pronoun needs recent research context.
    if names_results or _last_user_was_research_ask(history) or _last_assistant_looks_like_research(
        history
    ):
        return Intent(
            mode="research",
            skill_id="research",
            confidence=0.95,
            objective="open research findings on screen",
            reason="deterministic: show research findings",
            source="policy",
        )
    return None


def _last_assistant_was_optics_dump(history: list[dict[str, str]] | None) -> bool:
    if not history:
        return False
    for turn in reversed(history):
        if turn.get("role") != "assistant":
            continue
        text = (turn.get("content") or "").strip()
        if not text:
            continue
        try:
            from friday.assistant.reply_guard import looks_like_prompt_dump
            from friday.models.local import _looks_like_optics_dump

            return bool(looks_like_prompt_dump(text) or _looks_like_optics_dump(text))
        except Exception:  # noqa: BLE001
            return bool(
                re.search(
                    r"(?i)\b(here'?s a thinking process|analyze the request|"
                    r"the user\s*\(\s*boss\s*\)\s*says)\b",
                    text,
                )
            )
    return False


def _resolve_observe_answer_retry(
    msg: str, history: list[dict[str, str]] | None
) -> Intent | None:
    """After a screen-look dump, 'what's your answer' means look again — not chat clarify."""
    if not _last_assistant_was_optics_dump(history):
        return None
    if not re.search(
        r"(?i)\b("
        r"what('?s| is) (your |the )?answer|"
        r"tell me (your |the )?answer|"
        r"(that|this) was thinking|"
        r"now tell me|"
        r"what do you (actually )?see|"
        r"try again|look again"
        r")\b",
        msg,
    ):
        return None
    return Intent(
        mode="look",
        skill_id="observe",
        confidence=0.95,
        objective="What is on my screen right now?",
        reason="deterministic: retry observe after dump",
        source="policy",
    )


def _last_substantive_user(history: list[dict[str, str]] | None) -> str:
    if not history:
        return ""
    for turn in reversed(history):
        if turn.get("role") != "user":
            continue
        text = (turn.get("content") or "").strip()
        if not text or _CONFIRM_DO.search(text) or _CONFIRM_RESEARCH.search(text):
            continue
        if len(text) < 4:
            continue
        # Skip vague "do some research" — not a usable topic.
        if _is_vague_research_ask(text):
            continue
        return text
    return ""


def _assistant_offered_research_topic(last_a: str) -> str:
    """Pull the concrete topic Friday offered to look up."""
    if not (last_a or "").strip():
        return ""
    patterns = (
        r"(?i)\b(?:that|the|this)\s+(.{3,80}?)\s+research\b",
        r"(?i)\bresearch\s+(?:on|about|into|for)\s+(.{3,100}?)(?:\.|\?|$|,|\s+—)",
        r"(?i)\b(?:for the|about the|on the)\s+(.{5,90}?)(?:\s+plan|\s+landscape|\.|want me|,)",
        r"(?i)(?:shall i|i can|let me|want me to)\s+(.{12,160}?)(?:\?|$)",
    )
    for pat in patterns:
        m = re.search(pat, last_a)
        if not m:
            continue
        topic = re.sub(r"\s+", " ", m.group(1)).strip(" .?!,;:\"'")
        if len(topic) >= 4 and topic.lower() not in {"it", "that", "this", "them"}:
            return topic
    return ""


def _resolve_confirm_followup(
    msg: str, history: list[dict[str, str]] | None
) -> Intent | None:
    """Map short confirmations onto the prior real ask so we act instead of chatting."""
    confirm_research = bool(_CONFIRM_RESEARCH.search(msg))
    if not confirm_research and not _CONFIRM_DO.search(msg):
        return None
    prior = _last_substantive_user(history)
    last_a = ""
    if history:
        last_a = next(
            (t.get("content") or "" for t in reversed(history) if t.get("role") == "assistant"),
            "",
        )
    offered = _assistant_offered_research_topic(last_a)
    # Prefer what Friday just offered; then prior user topic with substance.
    objective = offered or prior
    if not objective:
        return None
    # Confirming a greeting / empty chat → ask for a real topic instead of googling "hey".
    if _is_vague_research_ask(objective) or (
        confirm_research
        and not offered
        and not _research_topic_residue(objective)
        and not _RESEARCH.search(objective)
    ):
        return Intent(
            mode="clarify",
            skill_id="chat",
            confidence=0.96,
            objective="What should I search for — give me a topic or question.",
            reason="deterministic: confirm research but no topic",
            source="policy",
        )
    if re.search(r"(?i)^\s*(hey|hi|hello|what'?s going on|how are you)\b", objective):
        return Intent(
            mode="clarify",
            skill_id="chat",
            confidence=0.96,
            objective="What should I search for — give me a topic or question.",
            reason="deterministic: confirm→stale greeting, ask topic",
            source="policy",
        )
    blob = f"{msg} {objective} {last_a}".lower()
    if confirm_research or _LEARN.search(objective) or _LEARN.search(last_a):
        if _LEARN.search(objective) or _LEARN.search(last_a):
            return Intent(
                mode="research",
                skill_id="research",
                confidence=0.93,
                objective=objective,
                reason="deterministic: confirm→learn",
                source="policy",
            )
        return Intent(
            mode="research",
            skill_id="research",
            confidence=0.93,
            objective=objective,
            reason="deterministic: confirm→research",
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
    r"notepad|chrome|excel|word|discord|spotify|settings|pc|computer|"
    r"freecad|taiga|cad|bracket|fillet|chamfer|fcstd|cube|sphere|cylinder|3d|create|build|model)\b",
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
