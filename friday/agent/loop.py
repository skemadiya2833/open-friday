"""
Core agent loop: Observe → Understand → Decide → Act (one) → Re-observe.

The vision model is the primary source of truth. Never chain actions without
re-checking the screen.
"""

from __future__ import annotations

import time

from friday.actions.executor import execute_action
from friday.agent.control import AgentController, set_controller
from friday.agent.memory import maybe_summarize_context
from friday.agent.planner import decide_next_action
from friday.agent.session import AgentSession
from friday.config import (
    LIVE_MODE,
    MAX_EMPTY_DECISIONS,
    MAX_ITERATIONS,
    MAX_STUCK_ACTIONS,
    OVERLAY_ENABLED,
    POST_ACTION_SETTLE_SECONDS,
    REQUIRE_FRESH_FRAME,
    STREAM_TICK_SECONDS,
)
from friday.types import AgentStatus, StepResult, VisionPayload
from friday.ui.events import emit
from friday.vision.feed import LiveScreenFeed


def run_agent(
    objective: str,
    *,
    controller: AgentController | None = None,
    use_overlay: bool | None = None,
) -> AgentStatus:
    """Run Friday until the objective is complete, halted, cancelled, or exhausted."""
    ctrl = controller or AgentController()
    set_controller(ctrl)
    show_overlay = OVERLAY_ENABLED if use_overlay is None else use_overlay

    print(f"\n[Friday] Starting task: {objective}\n")
    print("[Friday] Mode: vision-first observe → decide → one action → re-evaluate")
    emit("session_start", objective=objective)

    if show_overlay:
        from friday.ui import overlay
        overlay.start(total_steps=0, task_name=objective)

    session = AgentSession(objective=objective)
    feed = LiveScreenFeed(mask_overlay=show_overlay)

    try:
        if LIVE_MODE:
            feed.start()
            emit("status", status="live")
            if not feed.wait_until_ready(timeout=8.0):
                print("[Friday] Warning: live feed did not produce frames in time.")
        else:
            print("[Friday] LIVE_MODE=false — using one-shot capture each tick.")

        status = _loop(session, feed, ctrl, show_overlay)
        emit("session_end", status=status.value, objective=objective)
        return status
    finally:
        feed.stop()
        set_controller(None)
        if show_overlay:
            time.sleep(0.8)
            from friday.ui import overlay
            overlay.close()


def _check_control(ctrl: AgentController) -> AgentStatus | None:
    ctrl.wait_if_paused()
    if ctrl.should_stop():
        print("[Friday] Cancelled by operator.")
        emit("status", status="halt")
        return AgentStatus.HALTED
    return None


def _observe(feed: LiveScreenFeed) -> VisionPayload | None:
    """Return a vision payload from the live buffer or a one-shot capture."""
    vision = feed.snapshot_for_model()
    if vision is not None:
        return vision
    if LIVE_MODE:
        return None
    return feed.capture_oneshot()


def _wait_for_post_action_frame(
    feed: LiveScreenFeed,
    serial_before: int,
    settle: float,
) -> None:
    time.sleep(settle)
    if not LIVE_MODE or not feed.is_running:
        return
    fresh = feed.wait_for_fresh_frame(
        serial_before,
        timeout=settle + 2.0,
        require_fresh=REQUIRE_FRESH_FRAME,
    )
    if fresh is None and REQUIRE_FRESH_FRAME:
        print("[Friday] Fresh frame not ready — extending settle...")
        time.sleep(0.5)
        feed.wait_for_fresh_frame(
            serial_before,
            timeout=2.0,
            require_fresh=False,
        )


def _loop(
    session: AgentSession,
    feed: LiveScreenFeed,
    ctrl: AgentController,
    show_overlay: bool,
) -> AgentStatus:
    consecutive_empty = 0
    observe_failures = 0
    print("[Friday] Action loop started.")
    emit("status", status="running")

    while session.iteration < MAX_ITERATIONS:
        stop = _check_control(ctrl)
        if stop is not None:
            return stop

        print(f"\n[Friday] --- Observe tick {session.iteration + 1} ---")

        vision = _observe(feed)
        if vision is None:
            observe_failures += 1
            print("[Friday] No frames available yet, waiting...")
            if observe_failures >= 10:
                print("[Friday] Observation failed repeatedly. Stopping.")
                emit("status", status="error")
                return AgentStatus.FAILED
            time.sleep(STREAM_TICK_SECONDS)
            continue

        observe_failures = 0
        session.iteration += 1
        emit("tick", iteration=session.iteration)

        kind = "video" if vision.is_video else f"{vision.frame_count} frame(s)"
        print(
            f"[Friday] Observation: {kind} "
            f"({vision.native_size[0]}x{vision.native_size[1]} → "
            f"model {vision.image_size[0]}x{vision.image_size[1]})"
        )
        emit(
            "observation",
            iteration=session.iteration,
            kind=kind,
            native_size=vision.native_size,
            image_size=vision.image_size,
        )

        # Pause capture for the entire decide+act cycle so UI chrome / markers
        # cannot pollute the next observation buffer.
        feed.pause()
        terminal: AgentStatus | None = None
        acted = False
        serial_before = feed.frame_serial()
        settle = POST_ACTION_SETTLE_SECONDS

        try:
            if show_overlay:
                from friday.ui import overlay
                overlay.set_status("thinking")
            emit("status", status="thinking")

            decision = decide_next_action(session, vision)

            stop = _check_control(ctrl)
            if stop is not None:
                return stop

            if decision.observation:
                session.record_observation(decision.observation)
                print(f"[Friday] Sees: {decision.observation}")

            emit(
                "decision",
                message=decision.message,
                observation=decision.observation,
                step=decision.step.to_dict() if decision.step else None,
                iteration=session.iteration,
            )

            if show_overlay:
                from friday.ui import overlay
                steps = [decision.step.to_dict()] if decision.step else []
                overlay.update_plan(decision.message, steps)

            if decision.message:
                print(f"\n[Friday] {decision.message}")

            if not decision.has_action or decision.step is None:
                consecutive_empty += 1
                if consecutive_empty >= MAX_EMPTY_DECISIONS:
                    print("[Friday] No actionable decision on consecutive ticks. Stopping.")
                    emit("status", status="error")
                    return AgentStatus.FAILED
                print("[Friday] No action decided. Re-observing...")
                time.sleep(STREAM_TICK_SECONDS)
                continue

            consecutive_empty = 0
            step = decision.step
            print(f"[Friday] Next action: {step.action}")
            emit("action_start", step=step.to_dict(), iteration=session.iteration)

            if show_overlay:
                from friday.ui import overlay
                overlay.update(
                    1, step.action, "running",
                    step=step.to_dict(), iteration=session.iteration,
                )

            serial_before = feed.frame_serial()
            emit("status", status="running")
            result = execute_action(
                step,
                session=session,
                feed=feed,
                vision=vision,
                step_index=1,
            )
            acted = True
            session.record_action(step, result)
            maybe_summarize_context(session)
            emit(
                "action_end",
                step=step.to_dict(),
                result=result.value,
                history=list(session.history[-20:]),
                iteration=session.iteration,
            )

            if result == StepResult.COMPLETE:
                print("[Friday] Task complete.")
                if show_overlay:
                    from friday.ui import overlay
                    overlay.update(1, step.action, "complete", step=step.to_dict())
                emit("status", status="complete")
                terminal = AgentStatus.COMPLETED
            elif result == StepResult.HALT:
                print("[Friday] Execution halted by operator.")
                if show_overlay:
                    from friday.ui import overlay
                    overlay.update(1, step.action, "halt", step=step.to_dict())
                emit("status", status="halt")
                terminal = AgentStatus.HALTED
            else:
                settle = POST_ACTION_SETTLE_SECONDS
                if result == StepResult.REOBSERVE:
                    settle = max(settle, 1.0)

            if (
                terminal is None
                and MAX_STUCK_ACTIONS
                and session.stuck_count >= MAX_STUCK_ACTIONS
            ):
                print(
                    f"[Friday] {session.stuck_count} consecutive stuck actions "
                    "(skipped/errored) — stopping to avoid wasting compute."
                )
                emit("status", status="error")
                terminal = AgentStatus.FAILED
        finally:
            feed.resume()

        if terminal is not None:
            return terminal

        if acted:
            _wait_for_post_action_frame(feed, serial_before, settle)
            if show_overlay and feed.is_running:
                from friday.ui import overlay
                overlay.set_status("live")
            emit("status", status="live")
            time.sleep(STREAM_TICK_SECONDS)

        stop = _check_control(ctrl)
        if stop is not None:
            return stop

    print(
        f"\n[Friday] Reached iteration limit ({MAX_ITERATIONS}).\n"
        f"[Friday] Ensure the model is loaded in Ollama and responding."
    )
    emit("status", status="error")
    return AgentStatus.MAX_ITERATIONS
