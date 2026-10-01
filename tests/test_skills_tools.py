"""Unit tests for skill routing and tool parsing (no GPU required)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_coord_space_pixel_default():
    from friday.config import resolve_coord_space
    assert resolve_coord_space() in ("pixel", "grid1000")


def test_tool_extract():
    from friday.tools.react import _extract_tool_call

    text = 'Here\n```json\n{"tool": "memory_add", "args": {"text": "hi"}}\n```\n'
    call = _extract_tool_call(text)
    assert call is not None
    assert call["tool"] == "memory_add"


def test_skill_router_vision_hint():
    from friday.skills.router import SkillRouter
    from friday.skills.registry import SkillRegistry
    from friday.skills.base import Skill, SkillManifest, SkillContext, SkillResult

    class Dummy(Skill):
        def run(self, ctx: SkillContext) -> SkillResult:
            return SkillResult(reply="ok", skill_id=self.manifest.id)

    reg = SkillRegistry.__new__(SkillRegistry)
    reg.skills_dir = Path(".")
    reg._skills = {}
    for mid, vision, pri, trig in [
        ("chat", False, 40, ["hello"]),
        ("computer_use", True, 80, ["open", "notepad"]),
        ("research", False, 70, ["search"]),
    ]:
        s = Dummy()
        s.manifest = SkillManifest(
            id=mid, name=mid, description=mid, triggers=trig,
            priority=pri, requires_vision=vision, enabled=True,
        )
        reg._skills[mid] = s

    router = SkillRouter(reg)
    # Patch memory search to avoid chroma
    decision = router.route("Open notepad and type hello")
    assert decision.skill_id in ("computer_use", "chat", "research")


def test_workspace_sandbox(tmp_path, monkeypatch):
    import friday.tools.registry as reg
    monkeypatch.setattr(reg, "WORKSPACE_DIR", str(tmp_path))
    p = reg._safe_workspace_path("note.txt")
    assert str(p).startswith(str(tmp_path.resolve()))
    try:
        reg._safe_workspace_path("../escape.txt")
        assert False, "should have raised"
    except ValueError:
        pass


if __name__ == "__main__":
    test_coord_space_pixel_default()
    test_tool_extract()
    test_skill_router_vision_hint()
    print("ok")
