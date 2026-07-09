"""
Project Friday — vision-driven autonomous desktop & browser agent.

Usage:
    python main.py          # launches the GUI
    python main.py --cli    # classic terminal prompt
"""

from __future__ import annotations

import argparse
import os
import sys


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Friday — vision-driven agent")
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Run in terminal mode instead of the GUI",
    )
    parser.add_argument(
        "--low-end",
        action="store_true",
        help="Optimize for weak CPUs / limited VRAM (smaller frames, JPEG, fewer extras)",
    )
    parser.add_argument(
        "task",
        nargs="?",
        default=None,
        help="Optional task for CLI mode (skips interactive prompt)",
    )
    args = parser.parse_args(argv)

    if args.low_end:
        os.environ["LOW_END_MODE"] = "true"

    if args.cli or args.task:
        _run_cli(args.task)
    else:
        from friday.ui.app import launch_gui
        launch_gui()


def _run_cli(task: str | None) -> None:
    from friday.agent import run_agent
    from friday.types import AgentStatus

    objective = (task or "").strip()
    if not objective:
        objective = input("[Friday] On Your Service: ").strip()
    if not objective:
        print("[Friday] No task provided. Exiting.")
        return

    status = run_agent(objective)
    if status == AgentStatus.COMPLETED:
        print("\n[Friday] Done.")
    elif status == AgentStatus.HALTED:
        print("\n[Friday] Halted.")
    elif status == AgentStatus.MAX_ITERATIONS:
        print("\n[Friday] Stopped at iteration limit.")
    else:
        print(f"\n[Friday] Finished with status: {status.value}")


if __name__ == "__main__":
    main(sys.argv[1:])
