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

Mode = Literal[
    "talk", "look", "act", "cad", "remember", "research", "files", "schedule", "clarify"
]

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
# Optional leading filler/address so "uh Friday what's on my screen" still looks.
_ADDR = (
    r"(?:(?:hey|hi|hello|okay|ok|uh|um|erm|so|well|please|listen)\s+)*"
    r"(?:friday\s*[,:]?\s*)?"
)
_SCREEN_WORD = r"(?:screen|desktop|monitor|display)"
_WALLPAPER = r"(?:wallpaper|background|desktop\s+background|lock\s*screen)"
# Anchored look-only (classic phrasing).
_LOOK_ONLY = re.compile(
    rf"^\s*{_ADDR}("
    r"can you see|do you see|what (do you )?see|"
    r"(?:are you|you)\s+able\s+to\s+see|"
    r"what('?s| is) going on( here| on (my |the )?{_SCREEN_WORD})?|"
    r"what('?s| is) on (my |the )?{_SCREEN_WORD}|"
    rf"what('?s| is) (?:on |my |the )?{_WALLPAPER}|"
    rf"describe (?:my |the )?(?:{_SCREEN_WORD}|{_WALLPAPER})|"
    rf"look at (?:my )?(?:{_SCREEN_WORD}|{_WALLPAPER})|"
    r"tell me what you see|is (my )?{_SCREEN_WORD}|"
    rf"see (?:my |the )?{_SCREEN_WORD}|check (?:my |the )?{_SCREEN_WORD}|"
    rf"(?:take a |grab a )?screenshot|capture (?:my |the )?{_SCREEN_WORD}"
    r")\b",
    re.IGNORECASE,
)
# Loose screen-look — catches ASR filler / mid-sentence ("are you able to see my screen").
# Prefer this over chat/LLM classify so we never burn tokens deciding to look.
_SCREEN_LOOK = re.compile(
    rf"(?i)(?:"
    rf"\b(?:can|could|do|would|are)\s+you\s+(?:able\s+to\s+)?(?:see|look(?:\s+at)?)\b.{{0,48}}\b{_SCREEN_WORD}\b|"
    rf"\b(?:see|look\s+at|describe|check|watch)\s+(?:what(?:'s| is|s)?\s+on\s+)?(?:my\s+|the\s+)?{_SCREEN_WORD}\b|"
    rf"\bwhat(?:'s| is|s)\s+(?:going\s+on\s+)?(?:on\s+)?(?:my\s+|the\s+)?{_SCREEN_WORD}\b|"
    rf"\b(?:what(?:'s| is|s)|describe|look\s+at|see)\b.{{0,40}}\b{_WALLPAPER}\b|"
    rf"\bmy\s+{_WALLPAPER}\b|"
    rf"\b(?:take|grab|do)\s+(?:a\s+)?screenshot\b|"
    rf"\bcapture\s+(?:my\s+|the\s+)?{_SCREEN_WORD}\b|"
    rf"\bshow\s+me\s+(?:what(?:'s| is)\s+on\s+)?(?:my\s+|the\s+)?{_SCREEN_WORD}\b"
    rf")"
)
# "Closest Friday / MCU voice" — local TTS advice, never web legal theater.
_VOICE_PICK_ASK = re.compile(
    r"(?i)\b("
    r"(?:closest|best|good|recommend(?:ed)?)\s+voice.{"
    r"0,48}\b(?:friday|mcu|marvel|jarvis|karen)|"
    r"(?:friday|mcu|marvel|jarvis|karen).{0,48}\bvoice\b|"
    r"voice\s+(?:like|for|of)\s+(?:friday|jarvis|karen|mcu)|"
    r"which\s+voice.{"
    r"0,40}\b(?:friday|project|kokoro|edge)"
    r")\b"
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
# "webcam" ≠ optional "web" + "camera" (webcam is web+cam). Match both.
_CAM = r"(?:web\s?cams?|cameras?)"
# Webcam / desk camera (not screen).
_CAMERA_LOOK = re.compile(
    rf"(?:"
    rf"^\s*(?:what am i looking at|what('?s| is) on my desk|what('?s| is) in front of me|"
    rf"what am i doing(?: right now)?|what('?s| is) (?:he|she|this person) doing|"
    rf"look at (my )?desk|look at me|use the {_CAM}|through the {_CAM}|"
    rf"{_CAM}\b.*\?|(can you|could you) (see|look) (at )?(me|my desk|in front))"
    rf"|(?:show|open|display)\b.{{0,80}}\b(?:{_CAM}|what (?:you'?re|you are|it'?s) (?:seeing|looking at))"
    rf"|\b(?:what|what'?s|whats)\b.{{0,60}}\b(?:{_CAM}|seeing through)\b"
    rf"|\blook through\b.{{0,40}}\b{_CAM}\b"
    rf"|\b(?:can|could|do)\s+you\b.{{0,48}}\b(?:access|use|see|open|reach)\b.{{0,40}}\b{_CAM}\b"
    rf"|\b(?:can|could|do)\s+you\s+see\s+me\b"
    rf"|\bsee\s+me\s+on\s+(?:the\s+)?{_CAM}\b"
    rf"|\bam\s+i\s+(?:visible|on\s+(?:the\s+)?{_CAM}|in\s+(?:the\s+)?(?:web\s?)?cam)\b"
    rf"|\b(?:access|use)\b.{{0,24}}\b(?:my |the )?{_CAM}\b"
    rf"|\bis\s+(?:my |the )?{_CAM}\b.{{0,36}}\b(?:on|ready|working|available|armed)\b"
    rf")",
    re.IGNORECASE,
)
# Memory recall / store — beats CAD when the ask is about notes, not modeling.
_MEMORY_RECALL = re.compile(
    r"(?i)\b("
    r"(?:search|check|scan|look(?:\s+in)?|dig|query)\b.{0,48}\b(?:your\s+|my\s+|the\s+)?(?:memory|memories|notes)\b|"
    r"what\s+do\s+you\s+(?:remember|know|have)\b|"
    r"do\s+you\s+remember\b|"
    r"did\s+i\s+(?:ever\s+)?(?:tell|mention)\b|"
    r"what\s+did\s+i\s+(?:tell|say)\s+(?:you\s+)?(?:about\s+)?|"
    r"(?:from|in)\s+(?:your\s+)?(?:memory|notes)\b|"
    r"recall\s+(?:what|anything|my|the)\b"
    r")"
)
_MEMORY_STORE = re.compile(
    r"(?i)\b("
    r"remember\s+that\b|"
    r"remember\s+this\b|"
    r"don'?t\s+forget\s+(?:that|this)\b|"
    r"(?:store|save|note)\s+(?:this\s+|that\s+)?(?:in\s+)?(?:your\s+)?(?:memory|notes)\b|"
    r"(?:add|put)\s+(?:this\s+|that\s+)?(?:to|in)\s+(?:your\s+)?(?:memory|notes)\b|"
    r"make\s+a\s+note\s+(?:that|of)\b"
    r")"
)
_TASKS_FAST = re.compile(
    r"(?i)\b("
    r"remind\s+me\b|"
    r"remember\s+to\b|"
    r"set\s+(?:a\s+)?(?:reminder|alarm|timer)\b|"
    r"(?:what|whats|what'?s|show|list)\b.{0,40}\b(?:reminders?|alarms?|agenda|schedule|plan)\b|"
    r"(?:add|put|lock)\b.{0,48}\b(?:to\s+)?(?:my\s+|the\s+)?(?:plan|agenda|list)\b|"
    r"(?:plan|organise|organize)\s+(?:my\s+|the\s+)?(?:day|today|agenda)\b|"
    r"today'?s\s+(?:plan|agenda|tasks|schedule)\b|"
    r"on\s+(?:my\s+|the\s+)?(?:schedule|agenda|plan)\b|"
    r"we(?:'ll| will)\s+be\s+doing\b"
    r")"
)
_QUESTION = re.compile(
    r"^\s*(who|what|when|where|why|how|can you|could you|would you|is there|"
    r"are there|do you)\b.*\?\s*$",
    re.IGNORECASE,
)
_IMPERATIVE = re.compile(
    r"\b(open|launch|start|click|type|write|save|close|delete|install|download|"
    r"create|rename|move|copy|paste|run|execute|press|drag|scroll|"
    r"show|display|put|bring up|pull up)\b",
    re.IGNORECASE,
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
    re.IGNORECASE,
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


def _llm_classify(
    message: str, history: list[dict[str, str]] | None = None
) -> dict[str, Any] | None:
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
    # Tiny JSON-only classify — never a spoken reply. Keep tokens low.
    result = query_model_text(
        prompt,
        format_json=True,
        reasoning_mode=False,
        num_predict=64,
        num_ctx=min(1536, CHAT_NUM_CTX),
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
    if mode == "look" and skill not in {"observe", "camera"}:
        skill = "observe"
    try:
        conf = float(data.get("confidence") or 0.5)
    except TypeError, ValueError:
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


# Real desktop *actions* — not "show/display me the screen" (those are looks).
_ACT_NOT_LOOK = re.compile(
    r"(?i)\b("
    r"open|launch|start|click|type|write|save|close|delete|install|download|"
    r"create|rename|move|copy|paste|run|execute|press|drag|scroll|"
    r"put|bring up|pull up"
    r")\b"
)


def is_screen_look_utterance(message: str) -> bool:
    """True when the ask is desktop optics — capture screen, skip chat tokens."""
    msg = (message or "").strip()
    if not msg:
        return False
    screenshot = bool(
        re.search(
            rf"(?i)\b(?:take|grab|do)\s+(?:a\s+)?screenshot\b|"
            rf"\bcapture\s+(?:my\s+|the\s+)?{_SCREEN_WORD}\b",
            msg,
        )
    )
    if _ACT_NOT_LOOK.search(msg) and not screenshot:
        return False
    has_screen = bool(re.search(rf"(?i)\b{_SCREEN_WORD}\b", msg))
    has_cam_hw = bool(
        re.search(r"(?i)\b(?:web\s?cam(?:era)?|camera|my desk)\b", msg)
    )
    # "see me on the screen" → person/webcam, not desktop contents.
    if (
        re.search(r"(?i)\bsee\s+me\b", msg)
        and has_screen
        and not re.search(
            rf"(?i)\b(?:see|look(?:\s+at)?|describe|check)\s+(?:my\s+|the\s+)?{_SCREEN_WORD}\b",
            msg,
        )
    ):
        return False
    if has_screen and not has_cam_hw and (
        _SCREEN_LOOK.search(msg) or _LOOK_ONLY.search(msg)
    ):
        return True
    # "can you see" / "what do you see" with no camera cue → desktop.
    if (
        not has_cam_hw
        and not _CAMERA_LOOK.search(msg)
        and _LOOK_ONLY.search(msg)
    ):
        return True
    return bool(_SCREEN_LOOK.search(msg) and not has_cam_hw)


def is_camera_look_utterance(message: str) -> bool:
    """True when the ask is webcam/desk — never steal desktop screen looks."""
    msg = (message or "").strip()
    if not msg or is_screen_look_utterance(msg):
        return False
    return bool(_CAMERA_LOOK.search(msg))


def is_memory_utterance(message: str) -> bool:
    """True when the ask is local notes/memory — skip chat, run memory skill."""
    msg = (message or "").strip()
    if not msg:
        return False
    # "remember to …" is a reminder, not a memory store.
    if re.search(r"(?i)\bremember\s+to\b", msg):
        return False
    return bool(_MEMORY_STORE.search(msg) or _MEMORY_RECALL.search(msg))


def is_tasks_utterance(message: str) -> bool:
    """True when the ask is agenda / reminder — skip chat, run tasks skill."""
    msg = (message or "").strip()
    if not msg:
        return False
    if _TASKS_FAST.search(msg):
        return True
    try:
        from friday.tasks import reminders as _RM

        return bool(_RM.is_reminder_request(msg) or _RM.is_agenda_briefing(msg))
    except Exception:  # noqa: BLE001
        return False


def is_voice_pick_ask(message: str) -> bool:
    """True when they want a usable local TTS pick — not a Disney legal brief."""
    return bool(_VOICE_PICK_ASK.search((message or "").strip()))


def match_tool_fastpath(message: str) -> Intent | None:
    """
    Map a clear tool ask → skill with zero chat tokens.
    Used by deterministic classify and as a chat safety-net reroute.
    """
    msg = (message or "").strip()
    if not msg:
        return None

    if is_screen_look_utterance(msg):
        return Intent(
            mode="look",
            skill_id="observe",
            confidence=0.98,
            objective=msg,
            reason="fastpath: screen-look",
            source="policy",
        )
    if is_camera_look_utterance(msg):
        return Intent(
            mode="look",
            skill_id="camera",
            confidence=0.97,
            objective=msg,
            reason="fastpath: camera-look",
            source="policy",
        )
    if is_memory_utterance(msg):
        return Intent(
            mode="remember",
            skill_id="memory",
            confidence=0.96,
            objective=msg,
            reason="fastpath: memory",
            source="policy",
        )
    if is_tasks_utterance(msg):
        return Intent(
            mode="schedule",
            skill_id="tasks",
            confidence=0.96,
            objective=msg,
            reason="fastpath: tasks",
            source="policy",
        )
    # Research stays in the fuller deterministic path (topic / clarify / confirm
    # follow-ups). Fastpath here is only for skills that should never chat first.
    return None


def apply_policy(intent: Intent, message: str) -> Intent:
    """
    Deterministic safety rail. The model proposes; policy may veto Act.
    This is what prevents dumb mistakes architecturally.
    """
    msg = message.strip()

    # 1) Clear tool asks beat whatever the model proposed (observe/camera/memory/tasks).
    fast = match_tool_fastpath(msg)
    if fast is not None and (
        intent.skill_id != fast.skill_id or intent.mode != fast.mode
    ):
        return Intent(
            mode=fast.mode,
            skill_id=fast.skill_id,
            confidence=max(intent.confidence, fast.confidence),
            objective=msg,
            reason=f"policy: {fast.reason} (was {intent.mode}/{intent.skill_id})",
            needs_confirmation=False,
            source="policy",
            raw=intent.raw,
        )

    # 2) Sitrep without screen words can never become Act / observe.
    if _SITUATION_ASK.match(msg) and not re.search(
        rf"\b{_SCREEN_WORD}\b", msg, re.IGNORECASE
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

    # 4) Act requires imperative language OR high confidence + imperative objective.
    if intent.mode == "act" or intent.skill_id == "computer_use":
        # Measuring this PC is a real tool action even when phrased as a question.
        measure_hw = bool(
            "measure hardware" in (intent.reason or "")
            or re.search(
                r"\b(system specs?|hardware (?:status|check|report|info|specs?)|"
                r"system hardware|pc specs?|my (?:system )?specs?)\b",
                msg,
                re.IGNORECASE,
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
            if re.search(
                r"\b(screen|desktop|monitor|display|window|open apps?)\b",
                msg,
                re.IGNORECASE,
            ):
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
                re.IGNORECASE,
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


def _deterministic_intent(
    message: str, history: list[dict[str, str]] | None = None
) -> Intent | None:
    """
    Decide without the LLM when the utterance is unambiguous.
    This is the architectural fix: never ask a confused model a solved question.
    """
    msg = message.strip()
    if not msg:
        return Intent(
            mode="talk",
            skill_id="chat",
            confidence=1.0,
            objective=msg,
            reason="empty",
            source="policy",
        )

    # Tool fastpath first — zero chat/LLM tokens for clear observe/camera/memory/tasks.
    fast = match_tool_fastpath(msg)
    if fast is not None:
        return Intent(
            mode=fast.mode,
            skill_id=fast.skill_id,
            confidence=fast.confidence,
            objective=msg,
            reason=f"deterministic: {fast.reason}",
            source="policy",
        )

    # MCU / Friday voice pick — answer in chat with local Kokoro options (never research).
    if is_voice_pick_ask(msg):
        return Intent(
            mode="talk",
            skill_id="chat",
            confidence=0.97,
            objective=msg,
            reason="deterministic: local voice pick (not web)",
            source="policy",
        )

    # Skin / model / explicit camera-presence switches.
    presence_hit = _resolve_presence_intent(msg)
    if presence_hit is not None:
        return presence_hit

    # Sitrep / "what's going on" (no screen) → talk — never computer_use.
    if _SITUATION_ASK.match(msg) and not re.search(
        rf"\b{_SCREEN_WORD}\b", msg, re.IGNORECASE
    ):
        return Intent(
            mode="talk",
            skill_id="chat",
            confidence=0.95,
            objective=msg,
            reason="deterministic: situation",
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
        re.IGNORECASE,
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

    # Reminder follow-up after Friday asked "when should I remind…"
    from friday.tasks import reminders as _RM

    if history:
        last_a = next(
            (
                t.get("content") or ""
                for t in reversed(history)
                if t.get("role") == "assistant"
            ),
            "",
        )
        if re.search(
            r"when should I remind|say something like .in 20 minutes",
            last_a,
            re.IGNORECASE,
        ):
            echo = bool(
                re.search(
                    r"when should I remind|say something like|sure,? (?:boss|chief)",
                    msg,
                    re.IGNORECASE,
                )
            )
            if not echo and (_RM.parse_when(msg) or _RM.is_reminder_request(msg)):
                return Intent(
                    mode="schedule",
                    skill_id="tasks",
                    confidence=0.93,
                    objective=msg,
                    reason="deterministic: reminder follow-up",
                    source="policy",
                )

    # Conversational CAD: "make a 3d model…", plates/brackets with sizes, FreeCAD/Taiga.
    # Before HTML "build a page" / research. Skip filament / slicer shopping.
    # Also catch short solids ("make a cube") — otherwise chat invents .FCStd / desktop saves.
    if re.search(
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
        re.IGNORECASE,
    ) and not re.search(
        r"\b(filament|3d\s*print|printer|slicer|gcode|html(?:5)?|web\s*page|webpage|landing\s*page)\b",
        msg,
        re.IGNORECASE,
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
    if re.search(r"\bopen (the |my )?(research )?report\b", msg, re.IGNORECASE):
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
        re.IGNORECASE,
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
        re.IGNORECASE,
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
    # Never web-research local model / Ollama talk (qwen3.8, saluki lore, etc.).
    try:
        from friday.presence.modelswitch import looks_like_model_talk as _model_talk
    except Exception:  # noqa: BLE001
        _model_talk = lambda _m: False  # noqa: E731
    if (
        (_RESEARCH.search(msg) or _SEARCH_VERB.search(msg))
        and not _DESKTOP_TARGET.search(msg)
        and not _model_talk(msg)
        and not is_voice_pick_ask(msg)
        and not re.search(
            r"\b(open|launch|show)\b.{0,40}\bgoogle\s+(calendar|maps|drive|docs|mail|meet)\b",
            msg,
            re.IGNORECASE,
        )
        and not re.search(r"\b(your |my )?memory\b", msg, re.IGNORECASE)
        and not re.search(
            r"(?i)\b(tell me (some |an? )?(other )?tasks?|continue on our)\b", msg
        )
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
        re.IGNORECASE,
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
        re.IGNORECASE,
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
        re.IGNORECASE,
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
        re.IGNORECASE,
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
        re.IGNORECASE,
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
        return Intent(
            mode="talk",
            skill_id="chat",
            confidence=0.85,
            objective=msg,
            reason="deterministic: conversation",
            source="policy",
        )

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
    re.IGNORECASE,
)
# Broader search verb (needs a topic residue — otherwise clarify).
_SEARCH_VERB = re.compile(
    r"\b("
    r"search|searches|searching|look\s*ups?|looking\s+up|"
    r"look\s+(?:\w+\s+){0,3}up|"
    r"research(?:ing|es)?|google|"
    r"do\s+(?:a\s+|me\s+a\s+)?(?:little\s+|quick\s+|small\s+|fast\s+)?(?:web\s+|online\s+)?search"
    r")\b",
    re.IGNORECASE,
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
    if _NOT_A_SEARCH_TOPIC.match(msg or ""):
        return ""
    t = re.sub(
        r"(?i)\b("
        r"please|hey|hi|ok|okay|friday|boss|"
        r"can you|could you|would you|will you|"
        r"do (?:a |me a )?(?:little |quick |small |fast )?(?:web |google |online )?(?:search|lookup|research)|"
        r"search(?:es|ing)?(?: the web| google| online| for me)?|"
        r"look(?:ing)?\s*ups?|research(?:ing|es)?|google|find out|"
        r"for me|real quick|quickly|something|stuff|things?|a bit|a little|"
        r"the web|online|internet|about|regarding|concerning|"
        r"by yourself|yourself|on your own"
        r")\b",
        " ",
        msg or "",
    )
    t = re.sub(r"(?i)^\s*(for|on|of|to)\s+", "", t)
    t = re.sub(r"\s+", " ", t).strip(" .?!,;:\"'")
    # Need a real noun/phrase — not just "it" / "that" / meta fluff.
    if len(t) < 3 or t.lower() in {
        "it",
        "that",
        "this",
        "them",
        "those",
        "one",
        "about",
        "yourself",
        "by yourself",
        "on your own",
    }:
        return ""
    return t


def _is_vague_research_ask(msg: str) -> bool:
    if _VAGUE_SEARCH_ASK.match(msg or ""):
        return True
    if (
        _RESEARCH.search(msg or "") or _SEARCH_VERB.search(msg or "")
    ) and not _research_topic_residue(msg):
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
        (
            t.get("content") or ""
            for t in reversed(history)
            if t.get("role") == "assistant"
        ),
        "",
    )
    if not _ASKED_RESEARCH_TOPIC.search(last_a):
        return None
    if is_screen_look_utterance(msg) or is_camera_look_utterance(msg):
        return None
    try:
        from friday.presence.modelswitch import looks_like_model_talk
    except Exception:  # noqa: BLE001
        looks_like_model_talk = lambda _m: False  # noqa: E731
    if looks_like_model_talk(msg):
        return Intent(
            mode="talk",
            skill_id="presence",
            confidence=0.95,
            objective=msg,
            reason="deterministic: research topic was model talk → presence",
            source="policy",
        )
    # Pushback / ASR junk ("by yourself") is not a topic — cancel or look-retry.
    if _NOT_A_SEARCH_TOPIC.match(msg) or re.search(
        r"(?i)\b(never ?mind|cancel|forget it|stop)\b", msg
    ):
        look = _resolve_observe_answer_retry(msg, history)
        if look is not None:
            return look
        return Intent(
            mode="talk",
            skill_id="chat",
            confidence=0.9,
            objective=msg,
            reason="deterministic: research topic cancelled (not a topic)",
            source="policy",
        )
    topic = _research_topic_residue(msg)
    if len(topic) < 2:
        # Don't fall back to raw msg — that is how "by yourself" became a web query.
        return Intent(
            mode="clarify",
            skill_id="chat",
            confidence=0.9,
            objective="What should I search for — give me a real topic or question.",
            reason="deterministic: research topic empty/junk",
            source="policy",
        )
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
    re.IGNORECASE,
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
    re.IGNORECASE,
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
    if _last_assistant_looks_like_research(history) or _last_user_was_research_ask(
        history
    ):
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
    if (
        names_results
        or _last_user_was_research_ask(history)
        or _last_assistant_looks_like_research(history)
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


def _resolve_presence_intent(msg: str) -> Intent | None:
    """Skin / model / camera-presence utterances → presence skill."""
    if re.search(
        r"(?i)\b(?:switch|change|set)\b.{0,24}\b(?:to\s+)?(?:mode\s+)?"
        r"(friday|jarvis|ultron|vision|karen|edith|"
        r"f\.r\.i\.d\.a\.y\.?|j\.a\.r\.v\.i\.s\.?|k\.a\.r\.e\.n\.?|e\.d\.i\.t\.h\.?)\b|"
        r"\b(?:be|become)\s+(friday|jarvis|ultron|vision|karen|edith)\b|"
        r"\b(friday|jarvis|ultron|vision|karen|edith)\s+mode\b",
        msg,
    ):
        return Intent(
            mode="talk",
            skill_id="presence",
            confidence=0.97,
            objective=msg,
            reason="deterministic: presence skin switch",
            source="policy",
        )
    try:
        from friday.presence.modelswitch import (
            looks_like_model_switch,
            looks_like_model_talk,
        )
    except Exception:  # noqa: BLE001
        looks_like_model_switch = lambda _m: False  # noqa: E731
        looks_like_model_talk = lambda _m: False  # noqa: E731
    if (
        looks_like_model_talk(msg)
        or looks_like_model_switch(msg)
        or re.search(
            r"(?i)\b(?:switch|change|use|load|set|install|pull)\b.{0,48}\b(?:to\s+)?(?:model\s+)?"
            r"(qwen|gemma|llama|mistral|phi|deepseek|llava|minicpm|saluki)[\w.:-]*\b|"
            r"\b(?:switch|change)\b.{0,24}\bmodel\b|"
            r"\bwhat\s+model\b|\bwhich\s+model\b|\b(?:current|active)\s+model\b|"
            r"\b(qwen|gemma|llama|mistral|phi|deepseek|llava|minicpm)[\w.:-]*\d[\w.:-]*\b|"
            r"\bsaluki\b|"
            r"\bq\s+w\s+e\s+n\b|\bg\s+e\s+m\s+m\s+a\b",
            msg,
        )
    ):
        return Intent(
            mode="talk",
            skill_id="presence",
            confidence=0.96,
            objective=msg,
            reason="deterministic: presence model switch",
            source="policy",
        )
    # Explicit preference only — "can you see me" / "look at me" are camera looks.
    if re.search(
        r"(?i)\b(?:turn\s+on|enable|start|activate|turn\s+off|disable|stop)\b.{0,30}"
        r"\b(?:camera\s+)?presence\b|"
        r"\bcamera\s+presence\s+(?:on|off)\b|"
        r"\b(?:stop\s+looking\s+at\s+me|stop\s+watching\s+me)\b|"
        r"\b(?:watch\s+me\s+while|keep\s+(?:an\s+)?eye\s+on\s+me)\b|"
        r"\bpresence\s+mode\s+(?:on|off)\b",
        msg,
    ):
        return Intent(
            mode="talk",
            skill_id="presence",
            confidence=0.96,
            objective=msg,
            reason="deterministic: camera presence toggle",
            source="policy",
        )
    # Unknown callsign ("switch to Quinn", "become Quinn") — list skins; never invent.
    # Skip when the utterance is clearly a model switch (qwen/gemma ASR junk).
    if not looks_like_model_switch(msg) and re.search(
        r"(?i)\b(?:callsign|persona|skin)\b.{0,24}\b([A-Za-z][\w.-]{1,24})\b|"
        r"\bbecome\s+([A-Za-z][\w.-]{1,24})\b|"
        r"\bbe\s+([A-Za-z][\w.-]{1,24})\s+(?:mode|callsign|persona|skin)\b|"
        r"\b(?:switch|change)\s+to\s+([A-Za-z][\w.-]{1,24})\b",
        msg,
    ):
        return Intent(
            mode="talk",
            skill_id="presence",
            confidence=0.88,
            objective=msg,
            reason="deterministic: presence skin (unknown → list)",
            source="policy",
        )
    return None


_LOOK_PUSHBACK = re.compile(
    r"(?i)\b("
    r"smart enough|"
    r"(?:just |already )?do (?:that|it) already|"
    r"do that already|"
    r"just (?:do|look|capture|see)\b|"
    r"you should (?:have|be|already)|"
    r"why (?:didn'?t|aren'?t|won'?t|can'?t) you|"
    r"you (?:didn'?t|did not|aren'?t|won'?t|can'?t)\b.{0,40}\b"
    r"(?:look|see|capture|run|trigger|check)|"
    r"(?:didn'?t|did not)\s+(?:look|see|capture|run)\b|"
    r"take the (?:shot|frame|screenshot|picture)|"
    r"capture (?:it|already|now)|"
    r"look already|"
    r"see (?:it|me|the screen) already|"
    r"come on|"
    r"try again|look again|"
    r"fire it off|"
    r"what('?s| is) (your |the )?answer|"
    r"tell me (your |the )?answer|"
    r"(that|this) was thinking|"
    r"now tell me|"
    r"what do you (actually )?see|"
    r"you (?:didn'?t|never) (?:look|see|capture)|"
    # "do it by yourself" / ASR after a missed look — not a web topic.
    r"by yourself|on your own|figure it out"
    r")\b"
)
# Not real search topics (ASR junk, pushback, meta) — never web-research these.
_NOT_A_SEARCH_TOPIC = re.compile(
    r"(?i)^\s*(?:(?:hey|hi|okay|ok|uh|um)\s+)*(?:friday\s*[,:]?\s*)?"
    r"("
    r"by yourself|yourself|on your own|"
    r"(?:just )?do (?:it|that)(?:\s+by yourself|\s+yourself)?|"
    r"figure it out(?:\s+(?:by yourself|yourself))?|"
    r"you (?:decide|choose|pick|figure(?:\s+it\s+out)?)|"
    r"i don'?t know|idk|whatever|anything|something|"
    r"never ?mind|cancel|forget it|stop|no|"
    r"smart enough|come on|try again|"
    r"look(?:\s+at)?(?:\s+me|\s+my\s+screen)?|"
    r"see(?:\s+me|\s+my\s+screen)?"
    r")"
    r"\s*[.?!]*\s*$"
)


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
                    r"the user\s*\(\s*boss\s*\)\s*says|"
                    r"the user is challenging)\b",
                    text,
                )
            )
    return False


def _last_assistant_missed_look(history: list[dict[str, str]] | None) -> bool:
    """True when the last reply dodged a look (stand-by, muddy, dump, no capture)."""
    if _last_assistant_was_optics_dump(history):
        return True
    if not history:
        return False
    for turn in reversed(history):
        if turn.get("role") != "assistant":
            continue
        text = (turn.get("content") or "").strip()
        if not text:
            continue
        return bool(
            re.search(
                r"(?i)\b("
                r"i'?m with you|"
                r"what do you need|"
                r"standing by|"
                r"vision pass came back muddy|"
                r"couldn'?t (?:capture|read|see)|"
                r"say (?:look at me|what'?s on my (?:screen|desk))|"
                r"ask what'?s on my screen|"
                r"camera sensing is off|"
                r"couldn'?t arm the camera|"
                r"the user is challenging|"
                r"didn'?t automatically capture|"
                r"desktop vision agent|"
                r"vision agent|"
                r"vision tool|"
                r"tool wired up|"
                r"(?:didn'?t|did not) run this turn|"
                r"can'?t see your screen|"
                r"cannot see your screen|"
                r"in this chat channel"
                r")\b",
                text,
            )
        )
    return False


def _last_user_look_skill(history: list[dict[str, str]] | None) -> str | None:
    """Most recent user look ask → observe | camera."""
    if not history:
        return None
    for turn in reversed(history):
        if turn.get("role") != "user":
            continue
        text = (turn.get("content") or "").strip()
        if not text:
            continue
        if is_screen_look_utterance(text):
            return "observe"
        if is_camera_look_utterance(text):
            return "camera"
        # Skip pushback / tiny lines when scanning further back.
        if _LOOK_PUSHBACK.search(text) or len(text) < 4:
            continue
        break
    return None


def _resolve_observe_answer_retry(
    msg: str, history: list[dict[str, str]] | None
) -> Intent | None:
    """After a look ask, pushback / dump-retry means capture again — not a chat essay."""
    skill = _last_user_look_skill(history)
    if skill is None:
        return None

    pushback = bool(_LOOK_PUSHBACK.search(msg))
    classic_retry = bool(
        re.search(
            r"(?i)\b("
            r"what('?s| is) (your |the )?answer|"
            r"tell me (your |the )?answer|"
            r"(that|this) was thinking|"
            r"now tell me|"
            r"what do you (actually )?see|"
            r"try again|look again"
            r")\b",
            msg,
        )
    )
    if not pushback and not (
        classic_retry and _last_assistant_missed_look(history)
    ):
        return None

    objective = (
        "What do you see in front of the camera?"
        if skill == "camera"
        else "What is on my screen right now?"
    )
    return Intent(
        mode="look",
        skill_id=skill,
        confidence=0.96,
        objective=objective,
        reason=f"deterministic: retry {skill} after pushback/miss",
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
            (
                t.get("content") or ""
                for t in reversed(history)
                if t.get("role") == "assistant"
            ),
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
    if _RESEARCH.search(objective) or re.search(
        r"\b(reference|website|search|browser|sites?)\b", blob, re.IGNORECASE
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
        r"\b(screen|desktop|chrome|notepad|open|click|type)\b", blob, re.IGNORECASE
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
    re.IGNORECASE,
)
_NEEDS_LLM = re.compile(
    r"\b(screen|desktop|monitor|display|window|windows|app|apps|open|launch|start|click|type|write|save|close|delete|"
    r"file|files|folder|search|google|look ?up|research|browse|website|find|plan|agenda|task|tasks|memory|forget|download|"
    r"install|run|play|send|email|e-?mail|message|whatsapp|rename|move|copy|paste|scroll|press|drag|"
    r"notepad|chrome|excel|word|discord|spotify|settings|pc|computer|"
    r"freecad|taiga|cad|bracket|fillet|chamfer|fcstd|cube|sphere|cylinder|3d|create|build|model)\b",
    re.IGNORECASE,
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
