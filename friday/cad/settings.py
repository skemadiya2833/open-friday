"""CAD settings — Systems prefs first, then env, then auto-detect.

Friday and the Systems UI both read/write these via ``friday.runtime.prefs``.
"""

from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


CAD_PREF_KEYS = (
    "cad_enabled",
    "freecad_install",
    "freecad_s1_repo",
    "freecad_s1_python",
    "freecad_s1_model",
    "freecad_s1_port",
)

_DEFAULT_WIN_INSTALLS = (
    r"C:\Program Files\FreeCAD 1.1",
    r"C:\Program Files\FreeCAD 1.0",
    r"C:\Program Files\FreeCAD",
    r"C:\Program Files\FreeCAD 0.21",
)


@dataclass
class CadSettings:
    enabled: bool
    freecad_install: str
    freecad_exe: str
    freecad_python: str  # FreeCAD bundled python (for env hints)
    s1_repo: str
    s1_python: str
    s1_model: str
    s1_port: int
    freecad_found: bool
    repo_found: bool
    worker_found: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def default_vendor_repo() -> Path:
    from friday.config import DATA_DIR

    return Path(DATA_DIR) / "vendor" / "biome-s1"


def default_worker_python(repo: Path | None = None) -> Path:
    root = repo or default_vendor_repo()
    return root / ".venv" / "Scripts" / "python.exe"


def detect_freecad_installs() -> list[Path]:
    """Return existing FreeCAD roots (bin/freecad.exe present), preferred first."""
    found: list[Path] = []
    seen: set[str] = set()

    def _add(p: Path) -> None:
        try:
            p = p.expanduser().resolve()
        except Exception:
            return
        key = str(p).lower()
        if key in seen:
            return
        exe = p / "bin" / "freecad.exe"
        if not exe.is_file():
            # Sometimes install root IS bin's parent already checked; also accept freecadcmd
            if not (p / "bin" / "FreeCADCmd.exe").is_file() and not (p / "freecad.exe").is_file():
                return
        seen.add(key)
        found.append(p)

    for raw in _DEFAULT_WIN_INSTALLS:
        _add(Path(raw))

    prog = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    if prog.is_dir():
        for child in sorted(prog.glob("FreeCAD*")):
            _add(child)

    # Env override hints
    for key in ("FREECAD_INSTALL", "FREECAD_DIR", "FREECADHOME"):
        raw = (os.environ.get(key) or "").strip()
        if raw:
            _add(Path(raw))

    return found


def freecad_bin(install: Path) -> Path:
    bin_dir = install / "bin"
    if (bin_dir / "freecad.exe").is_file():
        return bin_dir
    return install


def freecad_exe_path(install: Path) -> Path | None:
    b = freecad_bin(install)
    for name in ("freecad.exe", "FreeCAD.exe"):
        p = b / name
        if p.is_file():
            return p
    return None


def freecad_bundled_python(install: Path) -> Path | None:
    b = freecad_bin(install)
    p = b / "python.exe"
    return p if p.is_file() else None


def _pref(key: str, default: Any = None) -> Any:
    try:
        from friday.runtime.prefs import get

        return get(key)
    except Exception:
        return default


def _env_bool(raw: str | None) -> bool | None:
    if raw is None:
        return None
    s = str(raw).strip().lower()
    if s in ("1", "true", "yes", "on"):
        return True
    if s in ("0", "false", "no", "off"):
        return False
    return None


def resolve() -> CadSettings:
    """Effective CAD settings (prefs → env → detect → vendor defaults)."""
    enabled_raw = _pref("cad_enabled", None)
    if enabled_raw is None:
        enabled = bool(_env_bool(os.getenv("FRIDAY_CAD")) or False)
    else:
        enabled = bool(enabled_raw)

    install_raw = str(_pref("freecad_install", "") or os.getenv("FREECAD_INSTALL") or "").strip()
    detected = detect_freecad_installs()
    if install_raw:
        install = Path(install_raw)
        if not freecad_exe_path(install) and detected:
            # Stale path — fall back to detect but keep record of configured string
            install = detected[0]
    elif detected:
        install = detected[0]
    else:
        install = Path(_DEFAULT_WIN_INSTALLS[0])

    exe = freecad_exe_path(install)
    bundled_py = freecad_bundled_python(install)

    repo_raw = str(_pref("freecad_s1_repo", "") or os.getenv("FREECAD_S1_REPO") or "").strip()
    repo = Path(repo_raw) if repo_raw else default_vendor_repo()

    worker_raw = str(_pref("freecad_s1_python", "") or os.getenv("FREECAD_S1_PYTHON") or "").strip()
    worker = Path(worker_raw) if worker_raw else default_worker_python(repo)

    model = str(_pref("freecad_s1_model", "") or os.getenv("FREECAD_S1_MODEL") or "shhivv/taiga-s1").strip()
    if not model:
        model = "shhivv/taiga-s1"

    try:
        port = int(_pref("freecad_s1_port", 8765) or os.getenv("FREECAD_S1_PORT") or 8765)
    except (TypeError, ValueError):
        port = 8765

    return CadSettings(
        enabled=enabled,
        freecad_install=str(install),
        freecad_exe=str(exe) if exe else "",
        freecad_python=str(bundled_py) if bundled_py else "",
        s1_repo=str(repo),
        s1_python=str(worker),
        s1_model=model,
        s1_port=port,
        freecad_found=bool(exe and exe.is_file()),
        repo_found=(repo / "freecad_s1").is_dir() or (repo / "pyproject.toml").is_file(),
        worker_found=worker.is_file(),
    )


def apply_patch(patch: dict[str, Any]) -> CadSettings:
    """Write CAD keys into Systems prefs and return resolved settings."""
    from friday.runtime.prefs import update

    clean = {k: v for k, v in patch.items() if k in CAD_PREF_KEYS}
    if clean:
        update(clean)
    return resolve()


def seed_from_detect(*, enable: bool = True) -> CadSettings:
    """Persist detected FreeCAD + default vendor paths into Systems prefs."""
    detected = detect_freecad_installs()
    install = detected[0] if detected else Path(_DEFAULT_WIN_INSTALLS[0])
    repo = default_vendor_repo()
    worker = default_worker_python(repo)
    return apply_patch({
        "cad_enabled": bool(enable),
        "freecad_install": str(install),
        "freecad_s1_repo": str(repo),
        "freecad_s1_python": str(worker),
        "freecad_s1_model": "shhivv/taiga-s1",
        "freecad_s1_port": 8765,
    })


_PATH_ANSWER = re.compile(
    r"(?i)(?:(?:set|use|path(?:\s+is)?|installed(?:\s+at)?|freecad(?:\s+is)?)\s*[:=]?\s*)?"
    r"([A-Za-z]:\\[^\r\n\"']+)"
)


def parse_path_from_message(message: str) -> str | None:
    m = _PATH_ANSWER.search(message or "")
    if not m:
        return None
    raw = m.group(1).strip().strip('"').rstrip(".,;")
    return raw if raw else None
