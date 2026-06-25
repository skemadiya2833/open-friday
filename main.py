import time

from config import OVERLAY_ENABLED, MAX_ITERATIONS
from engine.capture import capture_screen
from engine.router import create_high_level_plan, get_next_steps
from engine.executor import execute_step
from engine.session import TaskSession

if OVERLAY_ENABLED:
    from engine import overlay


def run_friday(objective: str) -> None:
    print(f"\n[Friday] Starting task: {objective}\n")

    if OVERLAY_ENABLED:
        overlay.start(total_steps=0, task_name=objective)

    try:
        _execute_loop(objective)
    finally:
        if OVERLAY_ENABLED:
            time.sleep(1.5)
            overlay.close()


def _execute_loop(objective: str) -> None:
    print("[Friday] Creating high-level plan...")
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
            session.plan_message,
            session.phases,
            session.current_phase_index,
        )

    consecutive_empty = 0

    while session.iteration < MAX_ITERATIONS:
        session.iteration += 1
        print(f"\n[Friday] --- Iteration {session.iteration} ---")

        print("[Friday] Capturing screen...")
        screen_b64, native_size, image_size, pil_image = capture_screen()
        if OVERLAY_ENABLED:
            overlay.update_screenshot(pil_image)

        native_w, native_h = native_size
        image_w, image_h = image_size
        print(f"[Friday] Screen resolution: {native_w}x{native_h}")
        if image_size != native_size:
            print(f"[Friday] Model image size: {image_w}x{image_h}")

        current_phase = session.current_phase
        if current_phase:
            print(
                f"[Friday] Current phase: {current_phase.get('title', '?')} "
                f"({session.current_phase_index + 1}/{len(session.phases)})"
            )

        plan = get_next_steps(session, screen_b64, native_size, image_size)

        message = plan.get("message", "")
        steps = plan.get("steps", [])
        if OVERLAY_ENABLED:
            overlay.update_plan(message, steps)
            overlay.update_strategy(
                session.plan_message,
                session.phases,
                session.current_phase_index,
            )

        if message:
            print(f"\n[Friday] {message}")
        print(f"[Friday] {len(steps)} next step(s).")

        if not steps:
            consecutive_empty += 1
            if OVERLAY_ENABLED:
                overlay.set_status("waiting")
            if consecutive_empty >= 2:
                print("[Friday] No steps returned on two consecutive iterations. Stopping.")
                break
            print("[Friday] No steps returned. Retrying with fresh screenshot...")
            continue

        consecutive_empty = 0

        if OVERLAY_ENABLED:
            overlay.start(total_steps=len(steps), task_name=objective)

        task_complete = False
        for step_index, step in enumerate(steps, start=1):
            action = step.get("action", "").upper()
            total = len(steps)

            if OVERLAY_ENABLED:
                overlay.update(
                    step_index,
                    action,
                    "running",
                    step=step,
                    iteration=session.iteration,
                )

            result = execute_step(step, step_index=step_index, total_steps=total)
            session.record_action(step, result)

            if result == "complete":
                print("[Friday] Task complete.")
                task_complete = True
                if OVERLAY_ENABLED:
                    overlay.update(
                        step_index,
                        action,
                        "complete",
                        step=step,
                        iteration=session.iteration,
                    )
                break

            if result == "halt":
                print("[Friday] Execution halted by operator.")
                if OVERLAY_ENABLED:
                    overlay.update(
                        step_index,
                        action,
                        "halt",
                        step=step,
                        iteration=session.iteration,
                    )
                return

            if result == "screenshot":
                print("[Friday] Pausing for fresh screenshot...")
                if OVERLAY_ENABLED:
                    overlay.update(
                        step_index,
                        action,
                        "waiting",
                        step=step,
                        iteration=session.iteration,
                    )
                break

            if OVERLAY_ENABLED:
                overlay.update(
                    step_index,
                    action,
                    "complete",
                    step=step,
                    iteration=session.iteration,
                )

            time.sleep(0.4)

        if task_complete:
            return

        if plan.get("phase_complete") and session.current_phase_index < len(session.phases) - 1:
            session.advance_phase()
            phase = session.current_phase or {}
            print(f"[Friday] Phase complete. Moving to: {phase.get('title', '?')}")
            if OVERLAY_ENABLED:
                overlay.update_strategy(
                    session.plan_message,
                    session.phases,
                    session.current_phase_index,
                )

    if session.iteration >= MAX_ITERATIONS:
        print(
            f"\n[Friday] Reached iteration limit ({MAX_ITERATIONS}) without completing the task.\n"
            f"[Friday] Check that your model is a vision-language model (e.g. minicpm-v) "
            f"and that the screen state is being read correctly."
        )


if __name__ == "__main__":
    task = input("[Friday] On Your Service: ").strip()
    if task:
        run_friday(task)
    else:
        print("[Friday] No task provided. Exiting.")
