import time

from config import LIVE_MODE, MAX_ITERATIONS, OVERLAY_ENABLED, STREAM_TICK_SECONDS
from engine.context import maybe_summarize_context
from engine.router import create_high_level_plan, get_next_steps
from engine.executor import execute_step
from engine.session import TaskSession
from engine.stream import LiveScreenFeed

if OVERLAY_ENABLED:
    from engine import overlay


def run_friday(objective: str) -> None:
    print(f"\n[Friday] Starting task: {objective}\n")
    if OVERLAY_ENABLED:
        overlay.start(total_steps=0, task_name=objective)

    feed = LiveScreenFeed()
    try:
        # Plan first (text-only) — live feed not running yet, no flicker.
        session = _build_session(objective)

        if LIVE_MODE:
            feed.start()
            if not feed.wait_until_ready(timeout=8.0):
                print("[Friday] Warning: live feed did not produce frames in time.")

        _action_loop(objective, session, feed)
    finally:
        feed.stop()
        if OVERLAY_ENABLED:
            time.sleep(1.5)
            overlay.close()


def _build_session(objective: str) -> TaskSession:
    print("[Friday] Creating high-level plan...")
    if OVERLAY_ENABLED:
        overlay.set_status("thinking")

    high_plan = create_high_level_plan(objective)
    session = TaskSession(
        objective=objective,
        phases=high_plan.get("phases", []),
        plan_message=high_plan.get("message", ""),
    )

    if session.plan_message:
        print(f"\n[Friday] Strategy: {session.plan_message}")

    for i, phase in enumerate(session.phases, start=1):
        title = phase.get("title", f"Phase {i}")
        goal = phase.get("goal", "")
        print(f"  Phase {i}: {title}" + (f" — {goal}" if goal else ""))

    if OVERLAY_ENABLED:
        overlay.update_strategy(
            session.plan_message, session.phases, session.current_phase_index,
        )
        overlay.set_status("running")

    return session


def _action_loop(objective: str, session: TaskSession, feed: LiveScreenFeed) -> None:
    consecutive_empty = 0
    print("[Friday] Live action loop started.")

    while session.iteration < MAX_ITERATIONS:
        session.iteration += 1
        print(f"\n[Friday] --- Stream tick {session.iteration} ---")

        vision = feed.snapshot_for_model()
        if vision is None:
            print("[Friday] No frames in live buffer yet, waiting...")
            time.sleep(STREAM_TICK_SECONDS)
            continue

        input_kind = "video" if vision.is_video else f"{vision.frame_count} frame(s)"
        print(
            f"[Friday] Live input: {input_kind} "
            f"({vision.native_size[0]}x{vision.native_size[1]} → "
            f"model {vision.image_size[0]}x{vision.image_size[1]})"
        )

        current_phase = session.current_phase
        if current_phase:
            print(
                f"[Friday] Phase: {current_phase.get('title', '?')} "
                f"({session.current_phase_index + 1}/{len(session.phases)})"
            )

        if OVERLAY_ENABLED:
            overlay.set_status("thinking")
        plan = get_next_steps(session, vision)

        if OVERLAY_ENABLED:
            overlay.sync_completed_steps(session.history)
            if feed.is_running:
                overlay.set_status("live")

        message = plan.get("message", "")
        steps = plan.get("steps", [])
        if OVERLAY_ENABLED:
            overlay.update_plan(message, steps)
            overlay.update_strategy(
                session.plan_message, session.phases, session.current_phase_index,
            )
        if message:
            print(f"\n[Friday] {message}")

        if not steps:
            consecutive_empty += 1
            if consecutive_empty >= 4:
                print("[Friday] No steps on four consecutive ticks. Stopping.")
                break
            print("[Friday] No steps returned. Waiting for next live frame...")
            time.sleep(STREAM_TICK_SECONDS)
            continue

        consecutive_empty = 0
        step = steps[0]
        action = step.get("action", "").upper()
        print(f"[Friday] Next action: {action}")

        if OVERLAY_ENABLED:
            overlay.update(1, action, "running", step=step, iteration=session.iteration)

        result = execute_step(
            step,
            step_index=1,
            total_steps=1,
            session=session,
            feed=feed,
            native_size=vision.native_size,
            image_size=vision.image_size,
        )
        session.record_action(step, result)
        maybe_summarize_context(session)

        if result == "screenshot":
            time.sleep(1.5)

        if OVERLAY_ENABLED:
            overlay.sync_completed_steps(session.history)
            if feed.is_running:
                overlay.set_status("live")

        if result == "complete":
            print("[Friday] Task complete.")
            if OVERLAY_ENABLED:
                overlay.update(1, action, "complete", step=step, iteration=session.iteration)
            return

        if result == "halt":
            print("[Friday] Execution halted by operator.")
            if OVERLAY_ENABLED:
                overlay.update(1, action, "halt", step=step, iteration=session.iteration)
            return

        if OVERLAY_ENABLED:
            overlay.update(1, action, "complete", step=step, iteration=session.iteration)

        time.sleep(STREAM_TICK_SECONDS)

        if plan.get("phase_complete") and session.current_phase_index < len(session.phases) - 1:
            session.advance_phase()
            phase = session.current_phase or {}
            print(f"[Friday] Phase complete. Moving to: {phase.get('title', '?')}")
            if OVERLAY_ENABLED:
                overlay.update_strategy(
                    session.plan_message, session.phases, session.current_phase_index,
                )

    if session.iteration >= MAX_ITERATIONS:
        print(
            f"\n[Friday] Reached iteration limit ({MAX_ITERATIONS}).\n"
            f"[Friday] Ensure the model is loaded in Ollama and responding."
        )


if __name__ == "__main__":
    task = input("[Friday] On Your Service: ").strip()
    if task:
        run_friday(task)
    else:
        print("[Friday] No task provided. Exiting.")
