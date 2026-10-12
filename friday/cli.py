"""Friday console entrypoint: ``friday``, ``friday doctor``, ``friday version``, ``friday serve``."""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading


def _quiet_hf_env() -> None:
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")


def run_control_center(*, tray: bool) -> None:
    from friday.config import SERVER_PORT, ensure_data_dirs, ui_host
    from friday.runtime.singleton import SingleInstanceError, acquire_instance_lock

    ensure_data_dirs()
    try:
        acquire_instance_lock()
    except SingleInstanceError as exc:
        print(f"[Friday] {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
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


def run_computer_use_cli(task: str | None) -> None:
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


def _cmd_version(_: argparse.Namespace) -> int:
    from friday import __version__

    print(__version__)
    return 0


def _cmd_doctor(args: argparse.Namespace) -> int:
    from friday.diagnostics.doctor import print_doctor_report, run_doctor

    report = run_doctor(probe_hardware=not args.no_hardware)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
        codes = {"pass": 0, "warn": 1, "fail": 2, "skip": 1}
        return codes.get(str(report.get("status", "warn")), 1)
    return print_doctor_report(report)


def _cmd_serve(args: argparse.Namespace) -> int:
    if args.low_end:
        os.environ["LOW_END_MODE"] = "true"
    tray = bool(args.tray) if args.tray else (not args.server_only)
    if args.server_only:
        tray = False
    run_control_center(tray=tray)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="friday",
        description="Friday — local-first personal AI assistant for Windows",
    )
    sub = parser.add_subparsers(dest="command")

    p_serve = sub.add_parser("serve", help="Start Control Center (default command)")
    p_serve.add_argument(
        "--server",
        dest="server_only",
        action="store_true",
        help="HTTP only (no system tray)",
    )
    p_serve.add_argument("--tray", action="store_true", help="Force system tray with server")
    p_serve.add_argument("--low-end", action="store_true", help="Optimize for weak CPUs / limited VRAM")
    p_serve.set_defaults(func=_cmd_serve)

    p_doctor = sub.add_parser("doctor", help="First-run diagnostics (never downloads models)")
    p_doctor.add_argument("--json", action="store_true", help="Print machine-readable JSON report")
    p_doctor.add_argument(
        "--no-hardware",
        action="store_true",
        help="Skip GPU / hardware inventory probe",
    )
    p_doctor.set_defaults(func=_cmd_doctor)

    p_ver = sub.add_parser("version", help="Print Friday version")
    p_ver.set_defaults(func=_cmd_version)

    return parser


def main(argv: list[str] | None = None) -> None:
    _quiet_hf_env()
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        # Bare `friday` → serve with tray
        args = argparse.Namespace(command="serve", server_only=False, tray=False, low_end=False)
        raise SystemExit(_cmd_serve(args))
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main(sys.argv[1:])
