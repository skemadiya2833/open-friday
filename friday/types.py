"""Shared types for the Friday agent loop."""

from __future__ import annotations

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
        return cls(
            action=str(raw.get("action", "")).upper(),
            description=str(raw.get("description") or ""),
            risky=bool(raw.get("risky", False)),
            x=_maybe_int(raw.get("x")),
            y=_maybe_int(raw.get("y")),
            x2=_maybe_int(raw.get("x2")),
            y2=_maybe_int(raw.get("y2")),
            text=_maybe_str(raw.get("text")),
            key=_maybe_str(raw.get("key")),
            keys=list(raw["keys"]) if isinstance(raw.get("keys"), list) else None,
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
