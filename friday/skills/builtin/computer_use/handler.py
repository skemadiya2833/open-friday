"""Bridge to the existing vision observe→decide→act loop — Act mode only."""

from __future__ import annotations

from friday.skills.base import Skill, SkillContext, SkillManifest, SkillResult

# Overlay/Tk-only traffic — never forward into the web SSE stream.
_SKIP_EVENTS = frozenset({"live_frame", "thinking_token", "thinking_clear"})


class SkillHandler(Skill):
    manifest = SkillManifest(
        id="computer_use",
        name="Computer Use",
        description="Vision desktop agent",
        requires_vision=True,
    )

    def run(self, ctx: SkillContext) -> SkillResult:
        # Last-line architectural guard: never seize the mouse for look-questions.
        from friday.assistant.intent import is_screen_look_utterance
        from friday.skills.registry import get_registry

        if is_screen_look_utterance(ctx.message):
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

        # Tools-first: open Notepad / specs / HTML / etc. without the vision loop (voice-friendly).
        from friday.agent.direct_tools import is_make_html_request, try_direct

        msg = ctx.message.strip()
        if is_make_html_request(msg):
            ctx.emit("activity", {"step": "direct", "message": "Writing HTML…"})
            ctx.emit("status", {"status": "acting"})

        direct = try_direct(msg)
        if direct.handled:
            # HTML / PowerShell / notepad — never seize the mouse. Final reply streams via done.
            if direct.tool == "shell_first":
                ctx.emit("activity", {"step": "shell", "message": "Running PowerShell…"})
                ctx.emit("status", {"status": "acting"})
            # Prefer a short activity line — never dump inventory into the HUD/TTS path.
            act_msg = {
                "list_peripherals": "Listing devices…",
                "show_specs_on_screen": "Collecting specs…",
                "shell_first": "Running PowerShell…",
            }.get(direct.tool or "", "") or (direct.message or "").split("\n")[0][:80]
            ctx.emit("activity", {"step": "direct", "message": act_msg or "Done"})
            ctx.emit("status", {"status": "idle"})
            reply = direct.message if direct.ok else f"That didn't work: {direct.message}"
            # Voice: hard-cap so TTS never reads a multi-line hardware dump.
            if ctx.voice_mode and reply and len(reply) > 280:
                reply = reply.split("\n")[0][:240].rstrip(" .") + "."
            return SkillResult(
                reply=reply,
                skill_id="computer_use",
                metadata={
                    "status": "completed" if direct.ok else "failed",
                    "direct": direct.tool,
                    "ok": direct.ok,
                },
            )

        from friday.agent.runs import RunBusyError, get_run_manager
        from friday.models.manager import get_model_manager

        get_model_manager().ensure_loaded("vision")
        objective = ctx.message.strip()
        from friday.agent.behavior import looks_multi_step, plan_preamble

        if looks_multi_step(objective):
            plan_note = plan_preamble(objective)
            ctx.emit("activity", {"step": "plan", "message": "Short plan before desktop steps…"})
            ctx.emit("thinking_set", {"text": plan_note[:600]})
            # Seed the run objective with the multi-step protocol so the vision loop sees it.
            objective = f"{plan_note}\n\nUSER OBJECTIVE:\n{objective}"
        ctx.emit("computer_use_start", {"objective": objective[:200]})
        # Quiet hint only — never dump the user utterance or open the RESULT card mid-run.
        ctx.emit("activity", {"step": "act", "message": "Working the desktop…"})
        ctx.emit("status", {"status": "acting"})

        # The run owns its controller and event log; only ITS events are forwarded here, so a
        # second chat session can never receive this run's events (and vice versa).
        try:
            run = get_run_manager().start(objective, exclusive=True)
        except RunBusyError as exc:
            return SkillResult(reply=f"I'm already driving the desktop. {exc}", skill_id="computer_use",
                               metadata={"refused": True})
        ctx.emit("run", {"run_id": run.id})
        for ev in run.iter_events():
            if ev["type"] in _SKIP_EVENTS:
                continue
            ctx.emit(ev["type"], {**ev["payload"], "run_id": run.id})
        status_name = run.status or "unknown"
        reply = f"Computer-use finished with status: **{status_name}**.\n\nObjective: {objective}"
        ctx.emit("computer_use_end", {"status": status_name})
        return SkillResult(
            reply=reply,
            skill_id="computer_use",
            metadata={"status": status_name, "objective": objective},
        )
