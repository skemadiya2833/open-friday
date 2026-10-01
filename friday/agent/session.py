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
    # (nx0, ny0, nx1, ny1) native-pixel focus box for crop-then-act.
    focus_box: tuple[int, int, int, int] | None = None
    # Prevent hallucinated click loops: fingerprint → consecutive count.
    last_action_fingerprint: str = ""
    repeat_action_count: int = 0

    def action_fingerprint(self, step: ActionStep) -> str:
        act = step.action.upper()
        if act in {"CLICK", "DOUBLE_CLICK", "RIGHT_CLICK", "HOVER", "SCROLL"}:
            x = step.x if step.x is not None else -1
            y = step.y if step.y is not None else -1
            # Quantize to absorb tiny aim jitter
            return f"{act}:{x // 12}:{y // 12}:{step.description or ''}"
        if act in {"TYPE", "PASTE", "WIN_SEARCH", "NAVIGATE", "RUN_SHELL"}:
            return f"{act}:{(step.text or step.query or step.url or '')[:80]}"
        return act

    def note_action_fingerprint(self, step: ActionStep) -> int:
        fp = self.action_fingerprint(step)
        if fp and fp == self.last_action_fingerprint:
            self.repeat_action_count += 1
        else:
            self.last_action_fingerprint = fp
            self.repeat_action_count = 1
        return self.repeat_action_count

    def set_focus_from_image(
        self,
        *,
        x: int,
        y: int,
        w: int,
        h: int,
        image_size: tuple[int, int],
        native_size: tuple[int, int],
        crop_origin: tuple[int, int] | None = None,
    ) -> tuple[int, int, int, int]:
        """Convert image-space box to native focus box and store it."""
        img_w, img_h = image_size
        nat_w, nat_h = native_size
        ox, oy = crop_origin or (0, 0)
        sx = nat_w / max(1, img_w)
        sy = nat_h / max(1, img_h)
        nx0 = int(ox + max(0, x - w // 2) * sx)
        ny0 = int(oy + max(0, y - h // 2) * sy)
        nx1 = int(ox + min(img_w, x + w // 2) * sx)
        ny1 = int(oy + min(img_h, y + h // 2) * sy)
        # Minimum useful crop (~280px) and pad
        pad = 40
        nx0 = max(0, nx0 - pad)
        ny0 = max(0, ny0 - pad)
        nx1 = min(native_size[0], max(nx0 + 280, nx1 + pad))
        ny1 = min(native_size[1], max(ny0 + 200, ny1 + pad))
        self.focus_box = (nx0, ny0, nx1, ny1)
        return self.focus_box

    def clear_focus(self) -> None:
        self.focus_box = None

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
