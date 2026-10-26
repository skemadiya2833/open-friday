"""Readiness probe for FreeCAD + Taiga-S1 (Systems prefs + auto-detect)."""

from __future__ import annotations

import socket
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class CadStatus:
    enabled: bool
    freecad_install: str
    freecad_found: bool
    repo_ok: bool
    repo_path: str | None
    socket_ok: bool
    port: int
    model: str
    freecad_s1_importable: bool
    worker_python: str | None
    worker_found: bool
    ready_to_build: bool
    blockers: list[str]
    can_auto_setup: bool
    can_launch: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "freecad_install": self.freecad_install,
            "freecad_found": self.freecad_found,
            "repo_ok": self.repo_ok,
            "repo_path": self.repo_path,
            "socket_ok": self.socket_ok,
            "port": self.port,
            "model": self.model,
            "freecad_s1_importable": self.freecad_s1_importable,
            "worker_python": self.worker_python,
            "worker_found": self.worker_found,
            "ready_to_build": self.ready_to_build,
            "blockers": list(self.blockers),
            "can_auto_setup": self.can_auto_setup,
            "can_launch": self.can_launch,
        }


def cad_enabled() -> bool:
    from friday.cad.settings import resolve

    return bool(resolve().enabled)


def s1_repo() -> Path | None:
    from friday.cad.settings import resolve

    cfg = resolve()
    p = Path(cfg.s1_repo)
    return p if cfg.repo_found else (p if p.is_dir() else None)


def s1_model() -> str:
    from friday.cad.settings import resolve

    return resolve().s1_model


def s1_port() -> int:
    from friday.cad.settings import resolve

    return int(resolve().s1_port)


def s1_python() -> str | None:
    from friday.cad.settings import resolve

    cfg = resolve()
    return cfg.s1_python if cfg.worker_found else (cfg.s1_python or None)


def _socket_open(host: str, port: int, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _can_import_freecad_s1(repo: Path | None) -> bool:
    try:
        import freecad_s1  # noqa: F401

        return True
    except Exception:
        pass
    if repo is None:
        return False
    root = str(repo.resolve())
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        import freecad_s1  # noqa: F401

        return True
    except Exception:
        return False


def probe_status() -> CadStatus:
    from friday.cad.settings import detect_freecad_installs, resolve

    cfg = resolve()
    repo = Path(cfg.s1_repo)
    port = int(cfg.s1_port)
    sock = _socket_open("127.0.0.1", port)
    importable = _can_import_freecad_s1(repo if cfg.repo_found else None)
    worker_ok = bool(cfg.worker_found and Path(cfg.s1_python).is_file())

    blockers: list[str] = []
    if not cfg.enabled:
        blockers.append("CAD is off — enable it in Systems → CAD, or ask me to turn it on.")
    if not cfg.freecad_found:
        blockers.append(
            "FreeCAD not found. Tell me the install folder (e.g. C:\\Program Files\\FreeCAD 1.1) "
            "or set it in Systems → CAD."
        )
    if not cfg.repo_found:
        blockers.append("Taiga/biome-s1 not installed yet — ask me to set up CAD, or use Systems → CAD → Setup.")
    if not worker_ok and not importable:
        blockers.append("Taiga worker Python missing — run CAD setup to create the venv with torch.")
    if not sock:
        blockers.append(
            f"FreeCAD Taiga server not listening on port {port} — ask me to launch FreeCAD, "
            "or open FreeCAD and run freecad_gui_server.FCMacro."
        )

    ready = (
        cfg.enabled
        and cfg.freecad_found
        and cfg.repo_found
        and sock
        and (importable or worker_ok)
    )
    return CadStatus(
        enabled=cfg.enabled,
        freecad_install=cfg.freecad_install,
        freecad_found=cfg.freecad_found,
        repo_ok=cfg.repo_found,
        repo_path=cfg.s1_repo if cfg.s1_repo else None,
        socket_ok=sock,
        port=port,
        model=cfg.s1_model,
        freecad_s1_importable=importable,
        worker_python=cfg.s1_python or None,
        worker_found=worker_ok,
        ready_to_build=ready,
        blockers=blockers,
        can_auto_setup=bool(detect_freecad_installs()) or cfg.freecad_found,
        can_launch=bool(cfg.freecad_found and cfg.repo_found),
    )
