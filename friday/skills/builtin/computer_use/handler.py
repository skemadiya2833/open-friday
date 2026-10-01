"""Bridge to the existing vision observe→decide→act loop — Act mode only."""

from __future__ import annotations

import json
import re
import threading
from typing import Any

from friday.skills.base import Skill, SkillContext, SkillManifest, SkillResult

_LOOK_ONLY = re.compile(
    r"^\s*(can you see|do you see|what (do you )?see|what('?s| is) (going )?on|"
    r"what('?s| is) on (my |the )?(screen|desktop)|describe (my |the )?(screen|desktop))\b",
    re.I,
)

# Overlay/Tk-only traffic — never forward into the web SSE stream.
_SKIP_EVENTS = frozenset({"live_frame", "thinking_token", "thinking_clear"})
_DROP_KEYS = frozenset({"image", "frame", "pil_image", "screenshot", "thumb"})


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if str(k) in _DROP_KEYS:
                continue
            cleaned = _jsonable(v)
            if cleaned is not None:
                out[str(k)] = cleaned
        return out
    # PIL / numpy-ish binary blobs must never hit SSE.
    if "Image" in type(value).__name__:
        return None
    try:
        json.dumps(value)
        return value
    except Exception:
        return str(value)


class SkillHandler(Skill):
    manifest = SkillManifest(
        id="computer_use",
        name="Computer Use",
        description="Vision desktop agent",
        requires_vision=True,
    )

    def run(self, ctx: SkillContext) -> SkillResult:
        # Last-line architectural guard: never seize the mouse for look-questions.
        if _LOOK_ONLY.search(ctx.message.strip()):
            from friday.skills.registry import get_registry

            observe = get_registry().get("observe")
            if observe is not None:
                return observe.run(ctx)
            return SkillResult(
                reply="That looks like a screen question — I won't click around. "
                      "Ask me to observe, or give an imperative task like "
                      "'Open Notepad and type hello'.",
                skill_id="computer_use",
                metadata={"refused": True},
            )

        from friday.agent.control import AgentController, set_controller
        from friday.agent.loop import run_agent
        from friday.models.manager import get_model_manager
        from friday.types import AgentStatus

        get_model_manager().ensure_loaded("vision")
        objective = ctx.message.strip()
        ctx.emit("computer_use_start", {"objective": objective})
        ctx.emit("activity", {"step": "act", "message": f"Desktop agent · {objective[:80]}"})
        ctx.emit("status", {"status": "acting"})

        controller = AgentController()
        set_controller(controller)
        status_holder: dict[str, AgentStatus] = {}

        def _run() -> None:
            try:
                status_holder["status"] = run_agent(
                    objective,
                    controller=controller,
                    use_overlay=True,
                )
            except Exception as exc:
                ctx.emit("error", {"message": str(exc)})
                status_holder["status"] = AgentStatus.FAILED
            finally:
                set_controller(None)

        # Bridge agent UI events into the chat SSE stream (JSON-safe only).
        from friday.ui.events import AgentEvent, get_bus

        def _bridge(event: AgentEvent) -> None:
            if event.type in _SKIP_EVENTS:
                return
            try:
                payload = event.payload if isinstance(event.payload, dict) else {}
                clean = _jsonable(payload)
                if not isinstance(clean, dict):
                    clean = {}
                ctx.emit(event.type, clean)
            except Exception:
                pass

        bus = get_bus()
        bus.subscribe_all(_bridge)

        thread = threading.Thread(target=_run, name="FridayComputerUse", daemon=True)
        thread.start()
        thread.join()
        bus.unsubscribe_all(_bridge)

        status = status_holder.get("status")
        status_name = status.value if status else "unknown"
        reply = f"Computer-use finished with status: **{status_name}**.\n\nObjective: {objective}"
        ctx.emit("computer_use_end", {"status": status_name})
        return SkillResult(
            reply=reply,
            skill_id="computer_use",
            metadata={"status": status_name, "objective": objective},
        )
