"""Single hardened shell runner shared by the `run_shell` tool and the agent's RUN_SHELL action.

Differences from the old implementation:
* no ``shell=True``; runs ``powershell.exe -NoProfile -NonInteractive -Command``
* working directory is forced inside the workspace sandbox (or a validated sub-path)
* timeout is bounded by policy; the whole process tree is killed on timeout
* output is truncated and secret-redacted before it is returned or logged
* stdin is closed so a command cannot block waiting for input
"""

from __future__ import annotations

import os
import subprocess
from typing import Any

from friday.safety.redact import redact_text
from friday.safety.policy import ShellPolicy
from friday.tools.paths import resolve_within
from friday.tools.types import ToolResult

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _kill_tree(pid: int) -> None:
    try:
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(pid)],
            capture_output=True, timeout=10, creationflags=_CREATE_NO_WINDOW,
        )
    except Exception:  # noqa: BLE001
        pass


def run_shell_command(
    command: str,
    *,
    policy: ShellPolicy,
    workspace: str,
    cwd: str | None = None,
    timeout: float | None = None,
) -> ToolResult:
    command = (command or "").strip()
    if not command:
        return ToolResult.error("Missing command")

    try:
        work_dir = resolve_within(workspace, cwd or ".")
    except ValueError as exc:
        return ToolResult.error(f"Invalid cwd: {exc}")
    os.makedirs(work_dir, exist_ok=True)

    limit = min(float(timeout or policy.timeout_seconds), policy.max_timeout_seconds)
    try:
        proc = subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
            cwd=str(work_dir),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=_CREATE_NO_WINDOW,
        )
    except FileNotFoundError:
        return ToolResult.error("powershell.exe not found")

    timed_out = False
    try:
        out, _ = proc.communicate(timeout=limit)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_tree(proc.pid)
        try:
            out, _ = proc.communicate(timeout=5)
        except Exception:  # noqa: BLE001
            out = ""

    text = redact_text(out or "")
    if len(text) > policy.max_output_chars:
        text = text[: policy.max_output_chars] + f"\n...[truncated {len(text) - policy.max_output_chars} chars]"

    meta: dict[str, Any] = {"exit_code": proc.returncode, "timed_out": timed_out, "cwd": str(work_dir)}
    if timed_out:
        return ToolResult.text_result(f"Timed out after {limit:.0f}s\n{text}".strip(), is_error=True, **meta)
    header = f"exit={proc.returncode}"
    return ToolResult.text_result(f"{header}\n{text}".strip(), is_error=proc.returncode != 0, **meta)
