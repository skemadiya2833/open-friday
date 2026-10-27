"""CAD skill — you describe the part; Friday plans, brings FreeCAD up, and builds."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from friday.skills.base import Skill, SkillContext, SkillManifest, SkillResult

_STATUS = re.compile(
    r"\b(cad|freecad|taiga)\b.{0,40}\b(status|ready|setup|installed)\b|"
    r"\b(is|are)\b.{0,20}\b(freecad|taiga|cad)\b.{0,30}\b(ready|working|set ?up)\b|"
    r"\b(setup|set up|enable|install|bootstrap)\b.{0,40}\b(freecad|taiga|cad)\b|"
    r"^\s*(cad|freecad|taiga)(\s+status)?\s*$",
    re.I,
)
_SETUP = re.compile(
    r"\b(set\s*up|setup|install|bootstrap|enable)\b.{0,40}\b(cad|freecad|taiga)\b|"
    r"\b(cad|freecad|taiga)\b.{0,40}\b(set\s*up|setup|install|bootstrap|enable)\b|"
    r"\byes\b.{0,20}\b(set\s*up|setup|enable|do it|install)\b|"
    r"^\s*(set\s*it\s*up|do\s*the\s*setup|enable\s*cad)\s*$",
    re.I,
)
_LAUNCH = re.compile(
    r"\b(launch|start|open)\b.{0,40}\b(freecad|taiga\s*server|cad\s*server)\b|"
    r"\b(freecad|taiga)\b.{0,20}\b(launch|start|open)\b",
    re.I,
)
_PLAN_ONLY = re.compile(
    r"\b(plan only|just (the )?plan|don't build|do not build|goal only|feature list)\b",
    re.I,
)
_ENABLE = re.compile(r"\b(enable|turn on|switch on)\b.{0,20}\b(cad|freecad|taiga)\b", re.I)
_DISABLE = re.compile(r"\b(disable|turn off|switch off)\b.{0,20}\b(cad|freecad|taiga)\b", re.I)


def _spoken_build_fail(detail: str) -> str:
    """Short voice-safe failure — never read HF progress, paths, or IoU dumps aloud."""
    low = (detail or "").lower()
    if (
        ("fetching" in low and "files" in low)
        or "hf hub" in low
        or "hf_token" in low
        or "taiga model" in low
    ):
        return "the CAD model was still downloading — say build again and I'll finish it"
    if "access is denied" in low or "create_directories" in low:
        return "FreeCAD couldn't save the file — I'm fixing the save path"
    if "socket" in low or "not listening" in low or "not reachable" in low:
        return "FreeCAD wasn't ready on the CAD port — I'll relaunch it next try"
    if "unexpected freecad reply" in low or "protocol" in low:
        return "the FreeCAD link glitched — retrying should clear it"
    # Keep one short clause; never dump stacks / tqdm.
    clean = re.sub(r"\s+", " ", (detail or "").strip())
    clean = re.sub(r"[\\|█#═\-_]{3,}", " ", clean)
    if len(clean) > 90 or not clean or any(ch in clean for ch in "{}[]<>"):
        return "I hit a snag in FreeCAD and I'm sorting it out"
    return clean


class SkillHandler(Skill):
    manifest = SkillManifest(
        id="cad",
        name="FreeCAD (Taiga-S1)",
        description="Plan and build FreeCAD parts with Taiga-S1",
        priority=88,
    )

    def run(self, ctx: SkillContext) -> SkillResult:
        from friday.cad.settings import apply_patch, parse_path_from_message
        from friday.cad.status import probe_status
        from friday.persona import owner_name

        msg = (ctx.message or "").strip()
        owner = owner_name()

        path = parse_path_from_message(msg)
        if path and re.search(r"(?i)freecad|cad|install|path|program files", msg):
            p = Path(path)
            if (p / "bin" / "freecad.exe").is_file() or (p / "freecad.exe").is_file():
                apply_patch({"freecad_install": str(p), "cad_enabled": True})
                return SkillResult(
                    reply=f"Saved FreeCAD as {p}. Describe the part and I'll build it.",
                    skill_id="cad",
                    metadata={"configured": True, "freecad_install": str(p)},
                )
            return SkillResult(
                reply=f"I couldn't find freecad.exe under {p}. Check the folder and tell me again.",
                skill_id="cad",
                metadata={"configured": False},
            )

        if _DISABLE.search(msg):
            apply_patch({"cad_enabled": False})
            return SkillResult(
                reply=f"CAD builds are off, {owner}. Say enable CAD anytime.",
                skill_id="cad",
                metadata={"cad_enabled": False},
            )

        if _ENABLE.search(msg) and not _SETUP.search(msg):
            apply_patch({"cad_enabled": True})
            return SkillResult(
                reply="CAD is on. Describe a part in mm (I'll assume sensible defaults) and I'll build it.",
                skill_id="cad",
                metadata={"cad_enabled": True},
            )

        if _SETUP.search(msg):
            return self._run_setup(ctx, owner)

        if _LAUNCH.search(msg):
            return self._run_launch(ctx, owner)

        if _STATUS.search(msg):
            st = probe_status()
            if st.ready_to_build:
                reply = (
                    f"CAD is ready, {owner}. Describe a part — sizes in mm, "
                    f"or tell me what to assume — and I'll build it in FreeCAD."
                )
            else:
                reply = (
                    f"Not fully hot yet, {owner}: {' '.join(st.blockers)} "
                    f"Describe a part anyway and I'll bring FreeCAD up myself."
                )
            return SkillResult(reply=reply, skill_id="cad", metadata={"status": st.as_dict()})

        return self._plan_and_build(ctx, owner, msg)

    def _run_setup(self, ctx: SkillContext, owner: str) -> SkillResult:
        from friday.cad.bootstrap import bootstrap

        ctx.emit("activity", {"step": "cad_setup", "message": "Setting up FreeCAD + Taiga…"})
        ctx.emit("status", {"status": "acting"})

        def progress(m: str) -> None:
            ctx.emit("activity", {"step": "cad_setup", "message": m[:120]})

        result = bootstrap(enable=True, on_progress=progress)
        ctx.emit("status", {"status": "idle"})
        return SkillResult(
            reply=result.message if result.ok else f"Setup hit a snag, {owner}: {result.message}",
            skill_id="cad",
            metadata={"setup": result.as_dict()},
        )

    def _run_launch(self, ctx: SkillContext, owner: str) -> SkillResult:
        from friday.cad.launch import ensure_gui_server

        ctx.emit("activity", {"step": "cad_launch", "message": "Launching FreeCAD…"})
        ctx.emit("status", {"status": "acting"})
        result = ensure_gui_server(wait_s=90.0)
        ctx.emit("status", {"status": "idle"})
        return SkillResult(
            reply=result.message if result.ok else f"Couldn't start FreeCAD, {owner}: {result.message}",
            skill_id="cad",
            metadata={"launch": result.as_dict()},
        )

    def _plan_and_build(self, ctx: SkillContext, owner: str, msg: str) -> SkillResult:
        from friday.cad.planner import plan_goal
        from friday.cad.ready import ensure_ready
        from friday.config import WORKSPACE_DIR

        plan_only = bool(_PLAN_ONLY.search(msg))

        ctx.emit("activity", {"step": "cad_plan", "message": "Planning the part…"})
        ctx.emit("status", {"status": "thinking"})
        plan = plan_goal(msg, history=ctx.history)

        if plan.clarify and not plan.goal:
            ctx.emit("status", {"status": "idle"})
            return SkillResult(
                reply=plan.clarify,
                skill_id="cad",
                metadata={"clarify": True, "raw": plan.raw},
            )

        assert plan.goal is not None
        goal = plan.goal
        # Compact symbols for HUD/metadata; plain words for anything spoken.
        summary = plan.summary or goal.summarize()
        spoken = goal.speak_summary()

        out = Path(WORKSPACE_DIR).expanduser().resolve() / "cad"
        out.mkdir(parents=True, exist_ok=True)
        tag = f"part_{int(time.time())}"
        goal_path = out / f"{tag}.goal.json"
        goal_path.write_text(json.dumps(goal.to_json(), indent=2), encoding="utf-8")

        if plan_only:
            ctx.emit("status", {"status": "idle"})
            return SkillResult(
                reply=f"Plan locked in, {owner}: {spoken}. Not building yet.",
                skill_id="cad",
                metadata={"planned": True, "built": False, "goal_path": str(goal_path), "summary": summary},
            )

        # Owner described a part → we bring FreeCAD/Taiga up ourselves, then build.
        ctx.emit("activity", {"step": "cad_ready", "message": f"Got it — {spoken}. Getting FreeCAD ready…"})
        ctx.emit("status", {"status": "acting"})

        def progress(m: str) -> None:
            # Activity feed can stay a bit technical; strip HF tqdm if it leaks.
            msg = m[:120]
            if "fetching" in msg.lower() and "files" in msg.lower():
                msg = "Loading CAD model…"
            ctx.emit("activity", {"step": "cad_ready", "message": msg})

        ready = ensure_ready(on_progress=progress, launch_wait_s=90.0)
        if not ready.ok:
            ctx.emit("status", {"status": "idle"})
            return SkillResult(
                reply=(
                    f"I lined up {spoken} in CAD, but FreeCAD wasn't ready yet — "
                    f"{_spoken_build_fail(ready.message)}. Say build again in a moment."
                ),
                skill_id="cad",
                metadata={
                    "planned": True,
                    "built": False,
                    "goal_path": str(goal_path),
                    "summary": summary,
                    "spoken": spoken,
                    "ready": ready.as_dict(),
                },
            )

        from friday.cad.runner import build_part

        ctx.emit("activity", {"step": "cad_build", "message": f"Building: {spoken}…"})

        def _step(n: int, action: str) -> None:
            ctx.emit("activity", {"step": "cad_step", "message": f"Step {n}: {action}"})

        result = build_part(goal, out_dir=out, tag=tag, on_step=_step)
        ctx.emit("status", {"status": "idle"})

        if result.ok:
            where = Path(result.fcstd).name if result.fcstd else goal_path.name
            reply = f"Done, {owner} — {spoken}. Saved as {where}."
        else:
            reply = (
                f"I had {spoken} ready in CAD but hit an issue — "
                f"{_spoken_build_fail(result.message)}. Trying to sort it; say build again if it stalls."
            )
        return SkillResult(
            reply=reply,
            skill_id="cad",
            metadata={
                "planned": True,
                "built": result.ok,
                "goal_path": str(goal_path),
                "summary": summary,
                "spoken": spoken,
                "fcstd": result.fcstd,
                "png": result.png,
                "steps": result.steps,
                "iou": result.iou,
                "ready": ready.as_dict(),
                "error": None if result.ok else (result.message or "")[:500],
            },
        )
