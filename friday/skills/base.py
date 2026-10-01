"""Skill base types and result streaming."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Iterator


@dataclass
class SkillManifest:
    id: str
    name: str
    description: str
    triggers: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    priority: int = 50
    requires_vision: bool = False
    system_overlay: str = ""
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "triggers": list(self.triggers),
            "tools": list(self.tools),
            "priority": self.priority,
            "requires_vision": self.requires_vision,
            "system_overlay": self.system_overlay,
            "enabled": self.enabled,
        }


@dataclass
class SkillContext:
    message: str
    session_id: str
    history: list[dict[str, str]] = field(default_factory=list)
    memory_hits: list[str] = field(default_factory=list)
    skill_override: str | None = None
    voice_mode: bool = False
    emit: Callable[[str, dict[str, Any]], None] = field(default=lambda *_: None)


@dataclass
class SkillResult:
    reply: str
    skill_id: str
    events: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class Skill:
    manifest: SkillManifest

    def run(self, ctx: SkillContext) -> SkillResult:
        raise NotImplementedError

    def run_stream(self, ctx: SkillContext) -> Iterator[dict[str, Any]]:
        """Yield SSE-style event dicts, ending with {type: done, result: ...}."""
        result = self.run(ctx)
        yield {"type": "token", "text": result.reply}
        yield {"type": "done", "result": {"reply": result.reply, "skill_id": result.skill_id, "metadata": result.metadata}}
