"""
Project Friday — local-first personal AI assistant + vision desktop agent.

Usage:
    python main.py              # Control Center (server + tray + browser UI)
    python main.py --server     # API + web UI only
    python main.py --gui        # Legacy tkinter Control Center
    python main.py --cli        # Classic terminal computer-use prompt
    python main.py --cli "Open Notepad"
"""

from __future__ import annotations

import argparse
import os
import sys
import threading


def main(argv: list[str] | None = None) -> None:
    # Quiet HF cache symlink noise on Windows before any voice/model imports.
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

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
        "task",
        nargs="?",
        default=None,
        help="Optional task for CLI mode",
    )
    args = parser.parse_args(argv)

    if args.low_end:
        os.environ["LOW_END_MODE"] = "true"

    if args.cli or args.task:
        _run_cli(args.task)
    elif args.gui:
        from friday.ui.app import launch_gui
        launch_gui()
    else:
        _run_control_center(tray=args.tray or not args.server)


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


def _run_control_center(*, tray: bool) -> None:
    from friday.config import SERVER_PORT, ensure_data_dirs, ui_host

    ensure_data_dirs()
    print(f"[Friday] Control Center → http://{ui_host()}:{SERVER_PORT}/")

    def _serve() -> None:
        from friday.server.app import run_server
        run_server()

    if tray:
        t = threading.Thread(target=_serve, name="FridayServer", daemon=True)
        t.start()
        from friday.ui.tray import start_tray
        start_tray(t)
    else:
        _serve()


if __name__ == "__main__":
    main(sys.argv[1:])
