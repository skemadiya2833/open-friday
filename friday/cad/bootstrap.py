"""Clone biome-s1, create a worker venv, and seed Systems CAD prefs."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


Progress = Callable[[str], None]


@dataclass
class BootstrapResult:
    ok: bool
    message: str
    steps: list[str] = field(default_factory=list)
    settings: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "message": self.message,
            "steps": list(self.steps),
            "settings": dict(self.settings),
        }


def _which_python312() -> str | None:
    """Prefer 3.12/3.11 for the Taiga worker (torch). Avoid Friday's 3.14 runtime."""
    py_launcher = shutil_which("py")
    if py_launcher:
        for ver in ("3.12", "3.11"):
            try:
                out = subprocess.run(
                    [py_launcher, f"-{ver}", "-c", "import sys; print(sys.executable)"],
                    capture_output=True,
                    text=True,
                    timeout=20,
                    check=False,
                )
                if out.returncode == 0 and out.stdout.strip():
                    return out.stdout.strip()
            except Exception:
                pass
    local = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python"
    for name in ("Python312", "Python311"):
        cand = local / name / "python.exe"
        if cand.is_file():
            return str(cand)
    hint = (os.environ.get("FREECAD_S1_BOOTSTRAP_PYTHON") or "").strip()
    if hint and Path(hint).is_file():
        return hint
    if sys.version_info[:2] >= (3, 11) and sys.version_info[:2] < (3, 14):
        return sys.executable
    return None


def shutil_which(name: str) -> str | None:
    from shutil import which

    return which(name)


def ensure_repo(repo: Path, *, on_progress: Progress | None = None) -> None:
    log = on_progress or (lambda _m: None)
    if (repo / "freecad_s1").is_dir() and (repo / "pyproject.toml").is_file():
        log(f"biome-s1 already present at {repo}")
        return
    repo.parent.mkdir(parents=True, exist_ok=True)
    if repo.exists() and not (repo / ".git").exists():
        # Incomplete folder — remove empty-ish and reclones
        pass
    url = "https://github.com/shhivv/biome-s1.git"
    log(f"Cloning {url} → {repo}")
    if repo.exists():
        subprocess.run(["git", "-C", str(repo), "pull", "--ff-only"], check=False, capture_output=True)
        if (repo / "freecad_s1").is_dir():
            return
    subprocess.run(
        ["git", "clone", "--depth", "1", url, str(repo)],
        check=True,
        capture_output=True,
        text=True,
    )


def ensure_worker_venv(repo: Path, *, on_progress: Progress | None = None) -> Path:
    log = on_progress or (lambda _m: None)
    venv_py = repo / ".venv" / "Scripts" / "python.exe"
    if venv_py.is_file():
        log(f"Worker venv already at {venv_py}")
    else:
        base = _which_python312()
        if not base:
            raise RuntimeError(
                "Need Python 3.11 or 3.12 to create the Taiga worker venv "
                "(Friday's 3.14 runtime can't host torch yet)."
            )
        log(f"Creating venv with {base}")
        subprocess.run([base, "-m", "venv", str(repo / ".venv")], check=True)
    log("Installing freecad_s1 + torch into worker venv (this can take a few minutes)…")
    subprocess.run([str(venv_py), "-m", "pip", "install", "-U", "pip", "wheel"], check=True)
    subprocess.run([str(venv_py), "-m", "pip", "install", "-e", str(repo)], check=True)
    # Smoke import
    probe = subprocess.run(
        [str(venv_py), "-c", "import freecad_s1, torch; print('ok')"],
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode != 0:
        raise RuntimeError(f"Worker import failed: {(probe.stderr or probe.stdout)[:500]}")
    log("Worker venv ready")
    return venv_py


def bootstrap(*, enable: bool = True, on_progress: Progress | None = None) -> BootstrapResult:
    """Full setup: detect FreeCAD, clone biome-s1, venv, write Systems prefs."""
    from friday.cad.settings import default_vendor_repo, detect_freecad_installs, seed_from_detect

    steps: list[str] = []

    def log(msg: str) -> None:
        steps.append(msg)
        if on_progress:
            on_progress(msg)

    try:
        detected = detect_freecad_installs()
        if not detected:
            return BootstrapResult(
                ok=False,
                message="FreeCAD not found under Program Files. Tell me the install folder and I'll save it.",
                steps=steps,
            )
        log(f"Found FreeCAD at {detected[0]}")
        repo = default_vendor_repo()
        ensure_repo(repo, on_progress=log)
        worker = ensure_worker_venv(repo, on_progress=log)
        settings = seed_from_detect(enable=enable)
        # Ensure worker path matches what we just built
        from friday.cad.settings import apply_patch

        settings = apply_patch({
            "freecad_s1_repo": str(repo),
            "freecad_s1_python": str(worker),
            "cad_enabled": bool(enable),
        })
        return BootstrapResult(
            ok=True,
            message=(
                f"CAD ready: FreeCAD at {settings.freecad_install}, "
                f"Taiga worker at {settings.s1_python}. "
                "I can launch FreeCAD's Taiga server when you ask to build a part."
            ),
            steps=steps,
            settings=settings.as_dict(),
        )
    except Exception as exc:  # noqa: BLE001
        return BootstrapResult(ok=False, message=str(exc), steps=steps)
