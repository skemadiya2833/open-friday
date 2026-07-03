"""Execution session — plan, phase tracking, compressed context, action history."""

from __future__ import annotations

from dataclasses import dataclass, field


def _step_summary(step: dict) -> str:
    act = (step.get("action") or "").upper()
    text = step.get("text")
    if text:
        preview = text[:40] + ("..." if len(text) > 40 else "")
        return f'{act} "{preview}"'
    desc = step.get("description") or ""
    return f"{act} — {desc}" if desc else act


@dataclass
class TaskSession:
    objective: str
    phases: list[dict] = field(default_factory=list)
    plan_message: str = ""
    current_phase_index: int = 0
    history: list[str] = field(default_factory=list)
    context_summary: str = ""
    iteration: int = 0
    actions_since_summary: int = 0

    @property
    def current_phase(self) -> dict | None:
        if not self.phases or self.current_phase_index >= len(self.phases):
            return None
        return self.phases[self.current_phase_index]

    def record_action(self, step: dict, result: str) -> None:
        summary = _step_summary(step)
        if result == "complete" and step.get("action", "").upper() == "COMPLETE":
            self.history.append(f"✓ {summary} (task done)")
        elif result == "halt":
            self.history.append(f"✗ {summary} (halted)")
        elif result == "error":
            self.history.append(f"✗ {summary} (error)")
        elif result == "skipped":
            self.history.append(f"⊘ {summary} (skipped)")
        else:
            self.history.append(f"✓ {summary}")
        self.actions_since_summary += 1

    def record_guard(self, message: str) -> None:
        self.history.append(f"⚠ {message}")

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

    def advance_phase(self) -> None:
        if self.current_phase_index < len(self.phases) - 1:
            self.current_phase_index += 1

    def format_phases(self) -> str:
        if not self.phases:
            return "(no phases)"
        lines: list[str] = []
        for i, phase in enumerate(self.phases):
            title = phase.get("title") or phase.get("goal") or f"Phase {i + 1}"
            goal = phase.get("goal") or phase.get("description") or ""
            if i < self.current_phase_index:
                status = "DONE"
            elif i == self.current_phase_index:
                status = "CURRENT"
            else:
                status = "PENDING"
            line = f"Phase {i + 1} [{status}]: {title}"
            if goal and goal != title:
                line += f" — {goal}"
            lines.append(line)
        return "\n".join(lines)

    def format_history(self, max_entries: int = 12) -> str:
        if not self.history:
            return "(nothing executed yet)"
        recent = self.history[-max_entries:]
        start = len(self.history) - len(recent) + 1
        return "\n".join(f"{start + i}. {entry}" for i, entry in enumerate(recent))

    def format_context(self) -> str:
        """Compressed context block for the VLM prompt."""
        parts: list[str] = []
        if self.context_summary:
            parts.append(f"PRIOR PROGRESS (summarized):\n{self.context_summary}")
        parts.append(f"RECENT ACTIONS:\n{self.format_history()}")
        return "\n\n".join(parts)
