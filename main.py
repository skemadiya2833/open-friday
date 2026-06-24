import time
from config import OVERLAY_ENABLED, MAX_ITERATIONS
from engine.capture import capture_screen
from engine.router import get_action_plan
from engine.executor import execute_step

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
            time.sleep(1.5)     # brief pause so the user sees the final state
            overlay.close()


def _execute_loop(objective: str) -> None:
    iteration = 0
    consecutive_empty = 0

    while iteration < MAX_ITERATIONS:
        iteration += 1
        print(f"\n[Friday] --- Iteration {iteration} ---")

        # Capture current screen state
        print("[Friday] Capturing screen...")
        screen_b64, native_size, image_size = capture_screen()
        native_w, native_h = native_size
        image_w, image_h = image_size
        print(f"[Friday] Screen resolution: {native_w}x{native_h}")
        if image_size != native_size:
            print(f"[Friday] Model image size: {image_w}x{image_h}")

        # Get action plan
        plan = get_action_plan(objective, screen_b64, native_size, image_size)

        message = plan.get("message", "")
        steps = plan.get("steps", [])

        if message:
            print(f"\n[Friday] {message}")
        print(f"[Friday] {len(steps)} step(s) planned.")

        if not steps:
            consecutive_empty += 1
            if consecutive_empty >= 2:
                print("[Friday] No steps returned on two consecutive iterations. Stopping.")
                break
            print("[Friday] No steps returned. Retrying with fresh screenshot...")
            continue
        else:
            consecutive_empty = 0

        if OVERLAY_ENABLED:
            overlay.start(total_steps=len(steps), task_name=objective)

        # Execute each step in the plan
        task_complete = False
        for step_index, step in enumerate(steps, start=1):
            result = execute_step(step, step_index=step_index, total_steps=len(steps))

            if result == "complete":
                print("[Friday] Task complete.")
                task_complete = True
                if OVERLAY_ENABLED:
                    overlay.update(step_index, "COMPLETE", "complete", step=step)
                break

            if result == "halt":
                print("[Friday] Execution halted by operator.")
                return

            if result == "screenshot":
                # Model requested a mid-plan screenshot — break inner loop and re-plan
                print("[Friday] Refreshing screen state mid-plan...")
                break

            time.sleep(0.4)

        if task_complete:
            return

    if iteration >= MAX_ITERATIONS:
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