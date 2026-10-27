"""Versioned multi-step plans with owner approve before execution.

Inspired by jarvis-os plan runner patterns; implemented natively for Friday.
CAD and desktop jobs can share this store.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

from friday.atomic import write_text_atomic

_lock = threading.RLock()
_store: "PlanStore | None" = None


def new_plan_id(prefix: str = "PLAN") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


class PlanStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, plan_id: str) -> Path:
        safe = "".join(c for c in plan_id if c.isalnum() or c in "-_")
        return self.root / f"{safe}.json"

    def list(self) -> list[dict[str, Any]]:
        out = []
        for p in sorted(self.root.glob("*.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                out.append(
                    {
                        "id": data.get("id"),
                        "title": data.get("title"),
                        "status": data.get("status"),
                        "version": data.get("version", 1),
                        "updated_at": data.get("updated_at"),
                    }
                )
            except Exception:  # noqa: BLE001
                continue
        return out

    def get(self, plan_id: str) -> dict[str, Any] | None:
        path = self._path(plan_id)
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def save(self, plan: dict[str, Any]) -> dict[str, Any]:
        plan = dict(plan)
        plan["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        write_text_atomic(self._path(str(plan["id"])), json.dumps(plan, indent=2) + "\n")
        return plan

    def create(
        self,
        title: str,
        steps: list[str] | list[dict[str, Any]],
        *,
        kind: str = "generic",
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        pid = new_plan_id()
        norm_steps = []
        for i, s in enumerate(steps, 1):
            if isinstance(s, dict):
                norm_steps.append({"n": i, "text": str(s.get("text") or s.get("step") or s), "status": "pending"})
            else:
                norm_steps.append({"n": i, "text": str(s), "status": "pending"})
        plan = {
            "id": pid,
            "title": title.strip()[:200],
            "kind": kind,
            "status": "draft",  # draft | approved | running | completed | failed | cancelled
            "version": 1,
            "steps": norm_steps,
            "meta": meta or {},
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "lineage": [pid],
        }
        return self.save(plan)

    def approve(self, plan_id: str) -> dict[str, Any]:
        plan = self.get(plan_id)
        if not plan:
            raise KeyError(plan_id)
        if plan.get("status") not in ("draft", "failed", "cancelled"):
            raise ValueError(f"cannot approve from status {plan.get('status')}")
        plan["status"] = "approved"
        return self.save(plan)

    def rerun(self, plan_id: str) -> dict[str, Any]:
        """Clone under a versioned id (PLAN-X → PLAN-X-2)."""
        src = self.get(plan_id)
        if not src:
            raise KeyError(plan_id)
        base = str(src["id"]).rsplit("-", 1)[0] if src.get("version", 1) > 1 else str(src["id"])
        ver = int(src.get("version") or 1) + 1
        clone = deepcopy(src)
        clone["id"] = f"{base}-{ver}"
        clone["version"] = ver
        clone["status"] = "draft"
        for s in clone.get("steps") or []:
            s["status"] = "pending"
        lineage = list(src.get("lineage") or [src["id"]])
        lineage.append(clone["id"])
        clone["lineage"] = lineage
        clone["parent_id"] = src["id"]
        return self.save(clone)


def get_plan_store() -> PlanStore:
    global _store
    with _lock:
        if _store is None:
            from friday.config import DATA_DIR

            _store = PlanStore(Path(DATA_DIR) / "plans")
        return _store
