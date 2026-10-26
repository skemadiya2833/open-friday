"""Taiga-S1 goal vocabulary (stdlib mirror — no freecad_s1 import required).

Feature kinds and param keys match freecad_s1.schema / goals.RECIPES so a
planned goal can be handed to Taiga-S1 without translation.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

GOAL_KINDS = frozenset({
    "base_box", "base_cyl", "base_hex", "base_ring",
    "boss_cyl", "boss_box", "hole", "hole_std", "pocket_rect",
    "polar_pattern", "linear_pattern", "mirror",
    "fillet_top", "fillet_vertical", "chamfer_top", "shell",
})

# Required numeric params per kind (others optional).
_REQUIRED: dict[str, frozenset[str]] = {
    "base_box": frozenset({"w", "d", "h"}),
    "base_cyl": frozenset({"r", "h"}),
    "base_hex": frozenset({"r", "h"}),
    "base_ring": frozenset({"ri", "ro", "h"}),
    "boss_cyl": frozenset({"r", "h", "x", "y"}),
    "boss_box": frozenset({"w", "d", "h", "x", "y"}),
    "hole": frozenset({"r", "x", "y"}),
    "hole_std": frozenset({"r", "x", "y"}),
    "pocket_rect": frozenset({"w", "d", "depth", "x", "y"}),
    "polar_pattern": frozenset({"n"}),
    "linear_pattern": frozenset({"n", "length"}),
    "mirror": frozenset(),
    "fillet_top": frozenset({"r"}),
    "fillet_vertical": frozenset({"r"}),
    "chamfer_top": frozenset({"size"}),
    "shell": frozenset({"t"}),
}

BASE_KINDS = frozenset({"base_box", "base_cyl", "base_hex", "base_ring"})


@dataclass
class GoalFeature:
    kind: str
    params: dict[str, float] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {"kind": self.kind, "params": {k: float(v) for k, v in self.params.items()}}


@dataclass
class ShapeInfo:
    valid: bool = False
    volume: float = 0.0
    area: float = 0.0
    bbox: tuple[float, float, float] = (0.0, 0.0, 0.0)
    n_faces: int = 0
    n_edges: int = 0
    n_solids: int = 0
    face_dirs: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        d = asdict(self)
        d["bbox"] = list(self.bbox)
        return d


@dataclass
class Goal:
    features: list[GoalFeature]
    level: int = 1
    scale: float = 1.0
    target: ShapeInfo = field(default_factory=ShapeInfo)

    def to_json(self) -> dict[str, Any]:
        return {
            "features": [f.to_json() for f in self.features],
            "level": int(self.level),
            "scale": float(self.scale),
            "target": self.target.to_json(),
        }

    @staticmethod
    def from_json(d: dict[str, Any]) -> Goal:
        feats = [
            GoalFeature(kind=str(f["kind"]), params={str(k): float(v) for k, v in (f.get("params") or {}).items()})
            for f in (d.get("features") or [])
        ]
        t = d.get("target") or {}
        bbox = t.get("bbox") or (0, 0, 0)
        if isinstance(bbox, list):
            bbox = tuple(float(x) for x in bbox[:3])
        target = ShapeInfo(
            valid=bool(t.get("valid", False)),
            volume=float(t.get("volume") or 0),
            area=float(t.get("area") or 0),
            bbox=(float(bbox[0]), float(bbox[1]), float(bbox[2])) if bbox else (0.0, 0.0, 0.0),
            n_faces=int(t.get("n_faces") or 0),
            n_edges=int(t.get("n_edges") or 0),
            n_solids=int(t.get("n_solids") or 0),
            face_dirs=list(t.get("face_dirs") or []),
        )
        return Goal(
            features=feats,
            level=int(d.get("level") or max(1, len(feats))),
            scale=float(d.get("scale") or 1.0),
            target=target,
        )

    def summarize(self) -> str:
        parts: list[str] = []
        for f in self.features:
            p = f.params
            if f.kind == "base_box":
                parts.append(f"plate {p.get('w')}×{p.get('d')}×{p.get('h')}")
            elif f.kind in ("base_cyl", "base_hex"):
                shape = "hex" if f.kind == "base_hex" else "cylinder"
                parts.append(f"{shape} Ø{2 * float(p.get('r', 0)):.1f} × {p.get('h')}")
            elif f.kind == "base_ring":
                parts.append(f"ring ri={p.get('ri')} ro={p.get('ro')} h={p.get('h')}")
            elif f.kind in ("hole", "hole_std"):
                parts.append(f"Ø{2 * float(p.get('r', 0)):.1f} hole at ({p.get('x')}, {p.get('y')})")
            elif f.kind == "pocket_rect":
                parts.append(f"pocket {p.get('w')}×{p.get('d')} depth {p.get('depth')}")
            elif f.kind == "boss_cyl":
                parts.append(f"boss Ø{2 * float(p.get('r', 0)):.1f} × {p.get('h')}")
            elif f.kind == "boss_box":
                parts.append(f"boss box {p.get('w')}×{p.get('d')}×{p.get('h')}")
            elif f.kind == "polar_pattern":
                parts.append(f"polar ×{int(p.get('n', 0))}")
            elif f.kind == "linear_pattern":
                parts.append(f"linear ×{int(p.get('n', 0))} over {p.get('length')}")
            elif f.kind == "mirror":
                parts.append("mirror")
            elif f.kind in ("fillet_top", "fillet_vertical"):
                parts.append(f"fillet r={p.get('r')}")
            elif f.kind == "chamfer_top":
                parts.append(f"chamfer {p.get('size')}")
            elif f.kind == "shell":
                parts.append(f"shell t={p.get('t')}")
            else:
                parts.append(f.kind)
        return " → ".join(parts) if parts else "(empty goal)"


def validate_goal(goal: Goal) -> list[str]:
    errs: list[str] = []
    if not goal.features:
        errs.append("goal needs at least one feature")
        return errs
    if goal.features[0].kind not in BASE_KINDS:
        errs.append(f"first feature must be a base (*{', '.join(sorted(BASE_KINDS))}*), got {goal.features[0].kind}")
    for i, f in enumerate(goal.features):
        if f.kind not in GOAL_KINDS:
            errs.append(f"feature[{i}] unknown kind '{f.kind}'")
            continue
        missing = _REQUIRED.get(f.kind, frozenset()) - set(f.params)
        if missing:
            errs.append(f"feature[{i}] {f.kind} missing params: {', '.join(sorted(missing))}")
        for k, v in f.params.items():
            try:
                fv = float(v)
            except (TypeError, ValueError):
                errs.append(f"feature[{i}] {f.kind}.{k} is not a number")
                continue
            if not math.isfinite(fv):
                errs.append(f"feature[{i}] {f.kind}.{k} is not finite")
            elif fv <= 0 and k != "x" and k != "y":
                # x/y may be negative (offset from center); counts/sizes must be > 0
                if k in ("n", "w", "d", "h", "r", "ri", "ro", "depth", "length", "size", "t"):
                    errs.append(f"feature[{i}] {f.kind}.{k} must be > 0")
    return errs


def estimate_target(goal: Goal) -> Goal:
    """Fill scale + rough target ShapeInfo from feature params (estimates are fine for Taiga)."""
    if not goal.features:
        return goal
    base = goal.features[0]
    p = base.params
    if base.kind == "base_box":
        w, d, h = float(p["w"]), float(p["d"]), float(p["h"])
        bbox = (w, d, h)
        vol = w * d * h
        scale = max(w, d, h)
    elif base.kind in ("base_cyl", "base_hex"):
        r, h = float(p["r"]), float(p["h"])
        bbox = (2 * r, 2 * r, h)
        vol = math.pi * r * r * h
        scale = max(2 * r, h)
    elif base.kind == "base_ring":
        ri, ro, h = float(p["ri"]), float(p["ro"]), float(p["h"])
        bbox = (2 * ro, 2 * ro, h)
        vol = math.pi * (ro * ro - ri * ri) * h
        scale = max(2 * ro, h)
    else:
        bbox, vol, scale = (40.0, 40.0, 10.0), 16000.0, 40.0

    # Patterns / bosses nudge volume roughly; exact IoU is scored live in FreeCAD.
    for f in goal.features[1:]:
        if f.kind in ("hole", "hole_std"):
            rr = float(f.params.get("r", 0))
            vol = max(0.0, vol - math.pi * rr * rr * (bbox[2] * 0.9))
        elif f.kind == "boss_cyl":
            rr = float(f.params.get("r", 0))
            hh = float(f.params.get("h", 0))
            vol += math.pi * rr * rr * hh
            bbox = (bbox[0], bbox[1], bbox[2] + hh * 0.5)
        elif f.kind == "boss_box":
            vol += float(f.params.get("w", 0)) * float(f.params.get("d", 0)) * float(f.params.get("h", 0))

    # Prefer an explicit positive scale from the planner; otherwise use the estimate.
    if float(goal.scale or 0) <= 1.0:
        goal.scale = float(scale or 1.0)
    goal.level = max(1, int(goal.level or 0), len(goal.features))
    goal.target = ShapeInfo(
        valid=True,
        volume=max(0.0, vol),
        area=2 * (bbox[0] * bbox[1] + bbox[1] * bbox[2] + bbox[0] * bbox[2]),
        bbox=bbox,
        n_faces=6,
        n_edges=12,
        n_solids=1,
        face_dirs=["+Z", "-Z", "+X", "-X", "+Y", "-Y"],
    )
    return goal
