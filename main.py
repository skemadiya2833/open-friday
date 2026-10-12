"""
Project Friday — local-first personal AI assistant + vision desktop agent.

Usage:
    python main.py              # Control Center (server + tray + browser UI)
    python main.py --server     # API + web UI only
    python main.py --gui        # Legacy tkinter Control Center
    python main.py --cli        # Classic terminal computer-use prompt
    python main.py --cli "Open Notepad"
    python main.py --doctor     # Diagnostics (same as ``friday doctor``)
"""

from __future__ import annotations

import argparse
import os
import sys


def main(argv: list[str] | None = None) -> None:
    from friday.cli import _quiet_hf_env, run_computer_use_cli, run_control_center

    _quiet_hf_env()

    parser = argparse.ArgumentParser(description="Friday — local personal AI assistant")
    parser.add_argument("--cli", action="store_true", help="Terminal computer-use mode")
    parser.add_argument("--gui", action="store_true", help="Legacy tkinter Control Center")
    parser.add_argument("--server", action="store_true", help="Run FastAPI Control Center only")
    parser.add_argument("--tray", action="store_true", help="Force system tray with server")
    parser.add_argument(
        "--low-end",
        action="store_true",
        help="Optimize for weak CPUs / limited VRAM",
    )
    parser.add_argument(
        "--doctor",
        action="store_true",
        help="Run first-run diagnostics (GPU, Ollama, models, ports) and exit",
    )
    parser.add_argument(
        "task",
        nargs="?",
        default=None,
        help="Optional task for CLI mode",
    )
    args = parser.parse_args(argv)

    if args.low_end:
        os.environ["LOW_END_MODE"] = "true"

    if args.doctor:
        from friday.diagnostics.doctor import print_doctor_report, run_doctor

        raise SystemExit(print_doctor_report(run_doctor()))

    if args.cli or args.task:
        run_computer_use_cli(args.task)
    elif args.gui:
        from friday.ui.app import launch_gui

        launch_gui()
    else:
        run_control_center(tray=args.tray or not args.server)


if __name__ == "__main__":
    main(sys.argv[1:])
