"""Select a skill — thin wrapper over the Intent brain (single source of truth)."""

from __future__ import annotations

from dataclasses import dataclass

from friday.skills.registry import SkillRegistry, get_registry


@dataclass
class RouteDecision:
    skill_id: str
    score: float
    reason: str
    alternatives: list[tuple[str, float]]


class SkillRouter:
    """
    Legacy entry point kept for tools/tests.
    Real routing lives in friday.assistant.intent (deterministic + LLM + policy).
    """

    def __init__(self, registry: SkillRegistry | None = None) -> None:
        self.registry = registry or get_registry()
        self._skills_indexed = False

    def route(self, message: str, *, override: str | None = None) -> RouteDecision:
        from friday.assistant.intent import classify_intent

        # Temporarily swap global registry if a test injected one.
        intent = classify_intent(message, override_skill=override)
        skill_id = intent.skill_id
        if self.registry.get(skill_id) is None:
            # Injected test registry may lack observe — fall back safely.
            if self.registry.get("chat"):
                skill_id = "chat"
            elif self.registry.list():
                skill_id = self.registry.list()[0].id
        return RouteDecision(
            skill_id,
            intent.confidence,
            f"{intent.mode}: {intent.reason}",
            [],
        )


_router: SkillRouter | None = None


def get_router() -> SkillRouter:
    global _router
    if _router is None:
        _router = SkillRouter()
    return _router
