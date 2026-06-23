import json
import time
from engine.capture import capture_screen
from engine.router import get_action_plan
from engine.executor import execute_step


def run_friday(objective: str):
    print(f"\n[Friday] Starting task: {objective}\n")

    iteration = 0
    max_iterations = 20  # Safety ceiling — prevents infinite loops

    while iteration < max_iterations:
        iteration += 1
        print(f"\n[Friday] --- Iteration {iteration} ---")

        # Capture current screen state
        print("[Friday] Capturing screen...")
        screen_b64, (width, height) = capture_screen()
        print(f"[Friday] Screen resolution: {width}x{height}")

        # Get action plan from local or cloud model
        plan = get_action_plan(objective, screen_b64)

        message = plan.get("message", "Processing...")
        steps = plan.get("steps", [])

        print(f"\n[Friday] {message}")
        print(f"[Friday] {len(steps)} step(s) planned.")

        if not steps:
            print("[Friday] No steps returned. Ending loop.")
            break

        # Execute each step
        for step in steps:
            result = execute_step(step)

            if result == "screenshot":
                # Model requested a fresh screenshot mid-plan — break inner loop
                print("[Friday] Refreshing screen state mid-plan...")
                break

            if result == "complete":
                print("[Friday] Task complete. Exiting.")
                return

            if result == "halt":
                print("[Friday] Execution halted by operator.")
                return

            time.sleep(0.5)

    print(f"\n[Friday] Reached iteration limit ({max_iterations}). Stopping.")


if __name__ == "__main__":
    task = input("[Friday] On Your Service: ").strip()
    run_friday(task)