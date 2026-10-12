"""Load and manage skill manifests + handlers."""

from __future__ import annotations

import importlib
import threading
from pathlib import Path
from typing import Any

import yaml

from friday.atomic import write_text_atomic
from friday.config import SKILLS_DIR
from friday.skills.base import Skill, SkillManifest


class SkillRegistry:
    def __init__(self, skills_dir: str | Path | None = None) -> None:
        self.skills_dir = Path(skills_dir or SKILLS_DIR)
        self._skills: dict[str, Skill] = {}
        self._lock = threading.Lock()
        self.reload()

    def reload(self) -> None:
        with self._lock:
            self._skills.clear()
            if not self.skills_dir.exists():
                return
            for child in sorted(self.skills_dir.iterdir()):
                if not child.is_dir() or child.name.startswith("_"):
                    continue
                skill = self._load_skill(child)
                if skill is not None:
                    self._skills[skill.manifest.id] = skill

    def _load_skill(self, folder: Path) -> Skill | None:
        manifest_path = folder / "manifest.yaml"
        if not manifest_path.exists():
            return None
        raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        manifest = SkillManifest(
            id=str(raw.get("id") or folder.name),
            name=str(raw.get("name") or folder.name),
            description=str(raw.get("description") or ""),
            triggers=[str(t) for t in (raw.get("triggers") or [])],
            tools=[str(t) for t in (raw.get("tools") or [])],
            priority=int(raw.get("priority") or 50),
            requires_vision=bool(raw.get("requires_vision", False)),
            system_overlay=str(raw.get("system_overlay") or ""),
            enabled=bool(raw.get("enabled", True)),
        )
        # Prefer package import path under friday.skills.builtin.<id>
        module_name = f"friday.skills.builtin.{folder.name}.handler"
        try:
            mod = importlib.import_module(module_name)
            cls = getattr(mod, "SkillHandler", None) or getattr(mod, "Handler", None)
            if cls is None:
                return None
            skill: Skill = cls()
            skill.manifest = manifest
            return skill
        except Exception as exc:
            print(f"[Skills] Failed to load {folder.name}: {exc}")
            return None

    def list(self) -> list[SkillManifest]:
        return [s.manifest for s in self._skills.values()]

    def get(self, skill_id: str) -> Skill | None:
        return self._skills.get(skill_id)

    def set_enabled(self, skill_id: str, enabled: bool) -> bool:
        skill = self._skills.get(skill_id)
        if not skill:
            return False
        skill.manifest.enabled = enabled
        # Persist to manifest.yaml
        folder = self.skills_dir / skill_id
        path = folder / "manifest.yaml"
        if path.exists():
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            raw["enabled"] = enabled
            write_text_atomic(path, yaml.safe_dump(raw, sort_keys=False))
        return True

    def update_manifest(self, skill_id: str, patch: dict[str, Any]) -> SkillManifest | None:
        skill = self._skills.get(skill_id)
        if not skill:
            return None
        m = skill.manifest
        if "description" in patch:
            m.description = str(patch["description"])
        if "triggers" in patch and isinstance(patch["triggers"], list):
            m.triggers = [str(t) for t in patch["triggers"]]
        if "priority" in patch:
            m.priority = int(patch["priority"])
        if "enabled" in patch:
            m.enabled = bool(patch["enabled"])
        folder = self.skills_dir / skill_id
        path = folder / "manifest.yaml"
        if path.exists():
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            raw.update({
                "description": m.description,
                "triggers": m.triggers,
                "priority": m.priority,
                "enabled": m.enabled,
            })
            write_text_atomic(path, yaml.safe_dump(raw, sort_keys=False))
        return m


_registry: SkillRegistry | None = None


def get_registry() -> SkillRegistry:
    global _registry
    if _registry is None:
        _registry = SkillRegistry()
    return _registry
