"""Presence skill — skin switch, model switch, camera presence on/off."""

from __future__ import annotations

import re

from friday.skills.base import Skill, SkillContext, SkillManifest, SkillResult

_SKIN_SWITCH = re.compile(
    r"(?i)\b(?:switch|change|set)\b.{0,24}\b(?:to\s+)?(?:mode\s+)?"
    r"(friday|jarvis|ultron|vision|karen|edith|"
    r"f\.r\.i\.d\.a\.y\.?|j\.a\.r\.v\.i\.s\.?|k\.a\.r\.e\.n\.?|e\.d\.i\.t\.h\.?)\b|"
    r"\b(?:be|become)\s+(friday|jarvis|ultron|vision|karen|edith)\b|"
    r"\b(friday|jarvis|ultron|vision|karen|edith)\s+mode\b",
)
_SKIN_SWITCH_ANY = re.compile(
    r"(?i)\b(?:callsign|persona|skin)\b.{0,24}\b([A-Za-z][\w.-]{1,24})\b|"
    r"\bbecome\s+([A-Za-z][\w.-]{1,24})\b|"
    r"\bbe\s+([A-Za-z][\w.-]{1,24})\s+(?:mode|callsign|persona|skin)\b|"
    r"\b(?:switch|change)\s+to\s+([A-Za-z][\w.-]{1,24})\b",
)
_KNOWN_SKINS = frozenset({"friday", "jarvis", "ultron", "vision", "karen", "edith"})
_MODEL_SWITCH = re.compile(
    r"(?i)\b(?:switch|change|use|load|set)\b.{0,28}\b(?:to\s+)?(?:model\s+)?"
    r"(qwen[\w.:-]*|gemma[\w.:-]*|llama[\w.:-]*|mistral[\w.:-]*|phi[\w.:-]*|"
    r"deepseek[\w.:-]*|llava[\w.:-]*|minicpm[\w.:-]*)\b|"
    r"\b(?:switch|change)\b.{0,16}\bmodel\b.{0,16}\b([\w.:-]{2,40})\b",
)
_MODEL_STATUS = re.compile(
    r"(?i)\bwhat\s+model\b|\bwhich\s+model\b|\bmodel\s+(?:are you|am i)\b|"
    r"\b(?:current|active)\s+model\b",
)
_PRESENCE_ON = re.compile(
    r"(?i)\b(?:turn\s+on|enable|start|activate)\b.{0,30}\b(?:camera\s+)?presence\b|"
    r"\bcamera\s+presence\s+on\b|"
    r"\b(?:see\s+me|look\s+at\s+me|watch\s+me)\b|"
    r"\bpresence\s+mode\s+on\b",
)
_PRESENCE_OFF = re.compile(
    r"(?i)\b(?:turn\s+off|disable|stop|deactivate)\b.{0,30}\b(?:camera\s+)?presence\b|"
    r"\bcamera\s+presence\s+off\b|"
    r"\bpresence\s+mode\s+off\b|"
    r"\bstop\s+looking\s+at\s+me\b",
)
_SKIN_STATUS = re.compile(
    r"(?i)\bwho\s+are\s+you\b|\bwhat\s+(?:mode|skin|persona|callsign)\b|"
    r"\b(?:current|active)\s+(?:mode|skin|persona|callsign)\b",
)


class SkillHandler(Skill):
    manifest = SkillManifest(
        id="presence",
        name="Presence",
        description="Switch skins, models, camera presence",
        priority=96,
    )

    def run(self, ctx: SkillContext) -> SkillResult:
        from friday.persona import owner_name

        msg = (ctx.message or "").strip()
        owner = owner_name()

        if _PRESENCE_OFF.search(msg):
            from friday.presence.camera_presence import set_camera_presence

            set_camera_presence(False, emit=ctx.emit)
            return SkillResult(
                reply=f"Camera presence off, {owner}. I won't glance unless you ask.",
                skill_id="presence",
                metadata={"camera_presence": False},
            )

        if _PRESENCE_ON.search(msg):
            from friday.presence.camera_presence import set_camera_presence

            set_camera_presence(True, emit=ctx.emit)
            return SkillResult(
                reply=(
                    f"Presence on, {owner}. I'll glance when we talk — "
                    "camera must stay enabled and armed in Systems."
                ),
                skill_id="presence",
                metadata={"camera_presence": True},
            )

        if _MODEL_STATUS.search(msg):
            from friday.presence.modelswitch import current_models

            m = current_models()
            return SkillResult(
                reply=f"Chat is on {m['chat_model']}; vision on {m['vision_model']}.",
                skill_id="presence",
                metadata=m,
            )

        skin_m = _SKIN_SWITCH.search(msg) or _SKIN_SWITCH_ANY.search(msg)
        if skin_m:
            from friday.presence.registry import apply_skin
            from friday.presence.skins import resolve_skin_id

            raw = next((g for g in skin_m.groups() if g), "")
            sid = resolve_skin_id(raw) or resolve_skin_id(msg)
            token = (raw or "").strip().lower()
            if not sid:
                # Don't invent Quinn / random personas — list the real callsigns.
                if (
                    token
                    and token not in _KNOWN_SKINS
                    and token
                    not in {
                        "mode",
                        "callsign",
                        "persona",
                        "skin",
                        "to",
                        "the",
                        "my",
                    }
                ):
                    return SkillResult(
                        reply=(
                            f"No '{token}' callsign, {owner}. "
                            "I have friday, jarvis, ultron, vision, karen, and edith."
                        ),
                        skill_id="presence",
                        metadata={"ok": False, "requested": token},
                    )
                return SkillResult(
                    reply=f"I know friday, jarvis, ultron, vision, karen, and edith, {owner}.",
                    skill_id="presence",
                )
            snap = apply_skin(sid, emit=ctx.emit)
            skin = snap["skin"]
            return SkillResult(
                reply=(
                    f"{skin['display_name']} mode, {owner} — same tools, different attitude. "
                    "Theatrical only; I won't touch anything unsafe."
                ),
                skill_id="presence",
                metadata={"presence": snap},
            )

        if _MODEL_SWITCH.search(msg) or re.search(
            r"(?i)\bswitch\b.{0,20}\b(qwen|gemma)\b", msg
        ):
            from friday.presence.modelswitch import (
                apply_chat_model,
                list_installed_tags,
                parse_switch_model_utterance,
                resolve_model_alias,
            )

            token = parse_switch_model_utterance(msg)
            if not token:
                m2 = re.search(r"(?i)\b(qwen[\w.:-]*|gemma[\w.:-]*)\b", msg)
                token = m2.group(1) if m2 else None
            if not token:
                return SkillResult(
                    reply=f"Say which model, {owner} — for example: switch to qwen, or switch to gemma.",
                    skill_id="presence",
                )
            tags = list_installed_tags()
            resolved = resolve_model_alias(token, tags=tags)
            if not resolved:
                sample = ", ".join(tags[:8]) if tags else "none listed"
                return SkillResult(
                    reply=(
                        f"I couldn't find an installed tag matching '{token}', {owner}. "
                        f"Ollama has: {sample}."
                    ),
                    skill_id="presence",
                    metadata={"ok": False, "requested": token, "tags": tags},
                )
            result = apply_chat_model(resolved, emit=ctx.emit)
            return SkillResult(
                reply=f"Switched chat to {result['chat_model']}, {owner}.",
                skill_id="presence",
                metadata=result,
            )

        if _SKIN_STATUS.search(msg):
            from friday.presence.registry import active_skin

            skin = active_skin()
            return SkillResult(
                reply=skin.identity_reply(owner),
                skill_id="presence",
                metadata={"skin": skin.as_dict()},
            )

        return SkillResult(
            reply=(
                f"I can switch skins (friday/jarvis/ultron/vision/karen/edith), "
                f"models (switch to qwen/gemma), or camera presence, {owner}."
            ),
            skill_id="presence",
        )
