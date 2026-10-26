"""Start FreeCAD with the Taiga-S1 GUI socket server."""

from __future__ import annotations

import os
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class LaunchResult:
    ok: bool
    message: str
    pid: int | None = None
    port: int = 8765
    already_running: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "message": self.message,
            "pid": self.pid,
            "port": self.port,
            "already_running": self.already_running,
        }


def _port_open(port: int, timeout: float = 0.35) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def _write_launcher_bat(cfg, *, repo: Path, macro: Path) -> Path:
    """Windows-friendly launcher so FREECAD_S1_REPO is set before FreeCAD starts."""
    from friday.config import DATA_DIR

    out = Path(DATA_DIR) / "cad" / "launch_taiga_server.bat"
    out.parent.mkdir(parents=True, exist_ok=True)
    install = Path(cfg.freecad_install)
    bin_dir = install / "bin"
    lines = [
        "@echo off",
        f'set "FREECAD_S1_REPO={repo.resolve()}"',
        f'set "FREECAD_S1_PORT={int(cfg.s1_port)}"',
    ]
    if bin_dir.is_dir():
        lines.append(f'set "FREECAD_LIB={bin_dir}"')
        if (bin_dir / "python.exe").is_file():
            lines.append(f'set "FREECAD_PYTHON={bin_dir / "python.exe"}"')
        lines.append(f'set "PATH={bin_dir};%PATH%"')
    lines.append(f'start "" "{cfg.freecad_exe}" "{macro.resolve()}"')
    out.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
    return out


def ensure_gui_server(*, wait_s: float = 90.0) -> LaunchResult:
    """If the Taiga socket is down, launch FreeCAD with freecad_gui_server.FCMacro."""
    from friday.cad.settings import resolve

    cfg = resolve()
    port = int(cfg.s1_port)
    if _port_open(port):
        return LaunchResult(
            ok=True,
            message=f"Taiga FreeCAD server already listening on {port}.",
            port=port,
            already_running=True,
        )

    if not cfg.freecad_found or not cfg.freecad_exe:
        return LaunchResult(
            ok=False,
            message="FreeCAD executable not found. Tell me the install folder and I'll save it.",
            port=port,
        )
    repo = Path(cfg.s1_repo)
    macro = repo / "scripts" / "freecad_gui_server.FCMacro"
    if not macro.is_file():
        return LaunchResult(
            ok=False,
            message=f"Missing {macro}. I'll set up Taiga if you ask me to build again.",
            port=port,
        )

    env = os.environ.copy()
    env["FREECAD_S1_REPO"] = str(repo.resolve())
    env["FREECAD_S1_PORT"] = str(port)
    install = Path(cfg.freecad_install)
    bin_dir = install / "bin"
    if bin_dir.is_dir():
        if (bin_dir / "python.exe").is_file():
            env["FREECAD_PYTHON"] = str(bin_dir / "python.exe")
        env["FREECAD_LIB"] = str(bin_dir)
        env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")

    bat = _write_launcher_bat(cfg, repo=repo, macro=macro)
    try:
        # Prefer the bat so a detached FreeCAD GUI inherits env cleanly on Windows.
        proc = subprocess.Popen(
            ["cmd.exe", "/c", str(bat)],
            env=env,
            cwd=str(bin_dir if bin_dir.is_dir() else install),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError:
        try:
            proc = subprocess.Popen(
                [cfg.freecad_exe, str(macro.resolve())],
                env=env,
                cwd=str(bin_dir if bin_dir.is_dir() else install),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            return LaunchResult(ok=False, message=f"Could not start FreeCAD: {exc}", port=port)

    deadline = time.time() + max(15.0, wait_s)
    while time.time() < deadline:
        if _port_open(port):
            return LaunchResult(
                ok=True,
                message=f"FreeCAD is up; Taiga server on {port}.",
                pid=getattr(proc, "pid", None),
                port=port,
            )
        time.sleep(0.75)

    # bat's `start` returns immediately — keep waiting on the socket only
    if _port_open(port):
        return LaunchResult(ok=True, message=f"Taiga server on {port}.", port=port)

    return LaunchResult(
        ok=False,
        message=(
            f"I started FreeCAD but the Taiga socket on {port} isn't up yet. "
            "I'll keep trying next build — or say \"launch FreeCAD\" again in a few seconds."
        ),
        pid=getattr(proc, "pid", None),
        port=port,
    )
