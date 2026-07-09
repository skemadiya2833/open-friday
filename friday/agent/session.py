"""Agent session state — objective, history, knowledge, adaptive notes."""

from __future__ import annotations

from dataclasses import dataclass, field

from friday.config import MAX_KNOWLEDGE_SEARCHES
from friday.types import ActionStep, KnowledgeNote, StepResult


def _step_summary(step: ActionStep) -> str:
    act = step.action.upper()
    text = step.text or step.query or step.url
    if text:
        preview = text[:40] + ("..." if len(text) > 40 else "")
        return f'{act} "{preview}"'
    if step.description:
        return f"{act} — {step.description}"
    return act


@dataclass
class AgentSession:
    """Mutable state for one user objective."""

    objective: str
    history: list[str] = field(default_factory=list)
    context_summary: str = ""
    iteration: int = 0
    actions_since_summary: int = 0
    knowledge: list[KnowledgeNote] = field(default_factory=list)
    knowledge_searches: int = 0
    last_observation: str = ""
    last_action_summary: str = ""
    stuck_count: int = 0

    def record_action(self, step: ActionStep, result: StepResult) -> None:
        summary = _step_summary(step)
        self.last_action_summary = f"{summary} → {result.value}"
        if result == StepResult.COMPLETE:
            self.history.append(f"✓ {summary} (task done)")
        elif result == StepResult.HALT:
            self.history.append(f"✗ {summary} (halted)")
        elif result == StepResult.ERROR:
            self.history.append(f"✗ {summary} (error)")
            self.stuck_count += 1
        elif result == StepResult.SKIPPED:
            self.history.append(f"⊘ {summary} (skipped)")
            self.stuck_count += 1
        else:
            self.history.append(f"✓ {summary}")
            self.stuck_count = 0
        self.actions_since_summary += 1

    def record_observation(self, text: str) -> None:
        self.last_observation = text.strip()

    def has_recent_win_search(self, app_text: str, lookback: int = 20) -> bool:
        needle = app_text.lower().strip()
        if not needle:
            return False
        for entry in self.history[-lookback:]:
            if not entry.startswith("✓"):
                continue
            if "WIN_SEARCH" in entry.upper() and needle in entry.lower():
                return True
        return False

    def can_knowledge_search(self) -> bool:
        return self.knowledge_searches < MAX_KNOWLEDGE_SEARCHES

    def add_knowledge(self, note: KnowledgeNote) -> None:
        self.knowledge.append(note)
        self.knowledge_searches += 1
        self.history.append(f"📚 Learned: {note.query} — {note.summary[:80]}")

    def format_history(self, max_entries: int = 12) -> str:
        if not self.history:
            return "(nothing executed yet)"
        recent = self.history[-max_entries:]
        start = len(self.history) - len(recent) + 1
        return "\n".join(f"{start + i}. {entry}" for i, entry in enumerate(recent))

    def format_knowledge(self) -> str:
        if not self.knowledge:
            return "(none)"
        lines = []
        for note in self.knowledge[-5:]:
            lines.append(f"- Q: {note.query}\n  A: {note.summary}")
        return "\n".join(lines)

    def format_context(self) -> str:
        parts: list[str] = []
        if self.context_summary:
            parts.append(f"PRIOR PROGRESS (summarized):\n{self.context_summary}")
        parts.append(f"RECENT ACTIONS:\n{self.format_history()}")
        if self.last_action_summary:
            parts.append(f"PREVIOUS ACTION (verify its effect on screen):\n{self.last_action_summary}")
        if self.knowledge:
            parts.append(f"GATHERED KNOWLEDGE:\n{self.format_knowledge()}")
        if self.last_observation:
            parts.append(f"PREVIOUS MODEL OBSERVATION (may be stale — trust the current frame):\n{self.last_observation}")
        if self.stuck_count >= 2:
            parts.append(
                "STUCK SIGNAL: Recent actions failed or were skipped. "
                "Re-assess the screen carefully. Consider WAIT, closing a popup, "
                "or KNOWLEDGE_SEARCH if you lack information."
            )
        return "\n\n".join(parts)
