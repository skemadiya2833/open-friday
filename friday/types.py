"""Shared types for the Friday agent loop."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal


class StepResult(str, Enum):
    """Outcome of executing a single action."""

    CONTINUE = "continue"
    REOBSERVE = "reobserve"
    SKIPPED = "skipped"
    COMPLETE = "complete"
    HALT = "halt"
    ERROR = "error"


class AgentStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    HALTED = "halted"
    FAILED = "failed"
    MAX_ITERATIONS = "max_iterations"


@dataclass(frozen=True)
class FramePacket:
    base64_png: str
    native_size: tuple[int, int]
    image_size: tuple[int, int]
    # Optional PIL image kept for video encoding; not required for inference.
    pil_image: Any = None


@dataclass
class VisionPayload:
    """Single observation sent to the vision model."""

    native_size: tuple[int, int]
    image_size: tuple[int, int]
    frame_b64_list: list[str]
    video_b64: str | None = None
    is_video: bool = False
    frame_count: int = 0
    # When set, image coords are relative to this native-pixel crop origin.
    crop_origin: tuple[int, int] | None = None
    crop_native_size: tuple[int, int] | None = None
    focused: bool = False

    @property
    def frame_b64(self) -> str | None:
        return self.frame_b64_list[-1] if self.frame_b64_list else None

    @property
    def latest_frame(self) -> str | None:
        return self.frame_b64


@dataclass
class ActionStep:
    """One intentional interaction decided by the vision model."""

    action: str
    description: str = ""
    risky: bool = False
    x: int | None = None
    y: int | None = None
    x2: int | None = None
    y2: int | None = None
    text: str | None = None
    key: str | None = None
    keys: list[str] | None = None
    button: str = "left"
    direction: str | None = None
    amount: int | None = None
    duration: float | None = None
    query: str | None = None
    url: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "action": self.action.upper(),
            "description": self.description,
            "risky": self.risky,
        }
        for key in (
            "x", "y", "x2", "y2", "text", "key", "keys", "button",
            "direction", "amount", "duration", "query", "url",
        ):
            value = getattr(self, key)
            if value is not None:
                data[key] = value
        data.update(self.extras)
        return data

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ActionStep:
        raw = dict(raw or {})
        nested = raw.get("args") or raw.get("arguments") or raw.get("params")
        if isinstance(nested, dict):
            raw = {**raw, **nested}
        known = {
            "action", "description", "risky", "x", "y", "x2", "y2",
            "text", "key", "keys", "button", "direction", "amount",
            "duration", "query", "url",
        }
        extras = {k: v for k, v in raw.items() if k not in known and not str(k).startswith("_")}
        # Preserve internal diagnostic keys
        for k, v in raw.items():
            if str(k).startswith("_"):
                extras[k] = v

        action = str(raw.get("action", "")).upper()
        keys = coerce_keys(raw.get("keys"))
        if not keys:
            keys = coerce_keys(raw.get("hotkey") or raw.get("chord") or raw.get("combo"))
        key = _maybe_str(raw.get("key"))
        # Models often put chords in "key" for HOTKEY, or a list in extras.
        if not keys and action == "HOTKEY":
            keys = coerce_keys(key) or coerce_keys(raw.get("text"))
            if keys and len(keys) > 1:
                key = None
        if action == "HOTKEY" and keys and len(keys) == 1 and not key:
            # Single-key HOTKEY → treat as PRESS_KEY for reliability.
            key = keys[0]
            keys = None
            action = "PRESS_KEY"
        if action == "PRESS_KEY" and key and ("+" in key or "," in key):
            chord = coerce_keys(key)
            if chord and len(chord) > 1:
                action = "HOTKEY"
                keys = chord
                key = None

        return cls(
            action=action,
            description=str(raw.get("description") or ""),
            risky=bool(raw.get("risky", False)),
            x=_maybe_int(raw.get("x")),
            y=_maybe_int(raw.get("y")),
            x2=_maybe_int(raw.get("x2")),
            y2=_maybe_int(raw.get("y2")),
            text=_maybe_str(
                raw.get("text")
                or raw.get("content")
                or raw.get("value")
                or raw.get("input")
                or raw.get("body")
                or raw.get("code")
            ),
            key=key,
            keys=keys,
            button=str(raw.get("button") or "left"),
            direction=_maybe_str(raw.get("direction")),
            amount=_maybe_int(raw.get("amount")),
            duration=_maybe_float(raw.get("duration")),
            query=_maybe_str(raw.get("query")),
            url=_maybe_str(raw.get("url")),
            extras=extras,
        )


@dataclass
class Decision:
    """Model output for one observe→decide cycle."""

    message: str
    step: ActionStep | None
    observation: str = ""
    confidence: float | None = None
    needs_knowledge: bool = False
    knowledge_query: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def has_action(self) -> bool:
        return self.step is not None and bool(self.step.action)


@dataclass
class KnowledgeNote:
    query: str
    summary: str
    source: str = "web_search"


OverlayState = Literal[
    "live", "running", "thinking", "aiming", "verifying",
    "waiting for approval", "complete", "halt", "error",
]


def _maybe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _maybe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _maybe_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


_KEY_ALIASES = {
    "control": "ctrl",
    "ctl": "ctrl",
    "cmd": "win",
    "command": "win",
    "windows": "win",
    "option": "alt",
    "return": "enter",
    "ret": "enter",
    "esc": "escape",
    "del": "delete",
    "bs": "backspace",
    "spacebar": "space",
}


def coerce_keys(value: Any) -> list[str] | None:
    """Normalize model hotkey payloads into a pyautogui key list.

    Accepts lists/tuples, or strings like ``ctrl+shift+p`` / ``ctrl, shift, p``.
    """
    if value is None:
        return None

    parts: list[str] = []
    if isinstance(value, (list, tuple)):
        for item in value:
            if item is None:
                continue
            token = str(item).strip()
            if not token:
                continue
            if len(token) > 1 and any(sep in token for sep in ("+", ",")):
                nested = coerce_keys(token)
                if nested:
                    parts.extend(nested)
                    continue
            parts.append(token)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        text = re.sub(r"^(hotkey|keys)\s*[:=]?\s*", "", text, flags=re.I).strip()
        if text.startswith("[") and text.endswith("]"):
            try:
                return coerce_keys(json.loads(text.replace("'", '"')))
            except Exception:
                text = text[1:-1]
        if "+" in text:
            parts = [p.strip() for p in text.split("+")]
        elif "," in text:
            parts = [p.strip() for p in text.split(",")]
        elif " " in text and len(text.split()) >= 2:
            tokens = text.split()
            modifiers = {"ctrl", "control", "alt", "shift", "win", "cmd"}
            if (
                all(re.fullmatch(r"[A-Za-z0-9_]+", t) for t in tokens)
                and any(t.lower() in modifiers for t in tokens)
            ):
                parts = tokens
            else:
                return None
        elif re.fullmatch(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)+", text):
            parts = text.split("-")
        else:
            parts = [text]
    else:
        return None

    normalized: list[str] = []
    for part in parts:
        key = part.strip().strip("\"'").lower()
        if not key:
            continue
        # Reject prose accidentally treated as a key
        if " " in key or len(key) > 20:
            return None
        normalized.append(_KEY_ALIASES.get(key, key))
    return normalized or None


_CHORD_IN_PROSE = re.compile(
    r"\b((?:ctrl|control|alt|shift|win|cmd|command)"
    r"(?:\s*[+\-]\s*[A-Za-z0-9]+)+)\b",
    re.IGNORECASE,
)


def extract_chord(text: Any) -> list[str] | None:
    """Pull a ctrl/alt/shift chord out of free-form description text."""
    if text is None:
        return None
    if not isinstance(text, str):
        return coerce_keys(text)
    direct = coerce_keys(text)
    if direct and len(direct) >= 2:
        return direct
    match = _CHORD_IN_PROSE.search(text)
    if match:
        return coerce_keys(match.group(1))
    return None
