"""Launch Google Artemis MCP (stdio) from Friday's vendor install.

Not a vendored copy of Artemis — only a thin launcher. Bootstrap clones
https://github.com/google/artemis into data/vendor/artemis when Systems
pref ``artemis_enabled`` is on.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_VENDOR = Path(os.environ.get("FRIDAY_ARTEMIS_DIR") or (_REPO / "data" / "vendor" / "artemis"))


def _venv_python(root: Path) -> Path | None:
    if sys.platform == "win32":
        cand = root / ".venv" / "Scripts" / "python.exe"
    else:
        cand = root / ".venv" / "bin" / "python"
    return cand if cand.is_file() else None


def main() -> int:
    if not _VENDOR.is_dir():
        sys.stderr.write(
            f"[Artemis] missing install at {_VENDOR}. "
            "Enable Systems → Artemis (phone MCP) and wait for bootstrap, "
            "or: git clone https://github.com/google/artemis.git \"{_VENDOR}\"\n"
        )
        return 2
    py = _venv_python(_VENDOR)
    if py is None:
        sys.stderr.write(
            f"[Artemis] no venv under {_VENDOR}. "
            "Run bootstrap (Systems → Artemis on) or: "
            f"cd {_VENDOR} && uv sync / python -m venv .venv && pip install -e .\n"
        )
        return 2
    os.chdir(_VENDOR)
    # mcp_server package lives at repo root.
    env_path = os.environ.get("PYTHONPATH", "")
    root = str(_VENDOR.resolve())
    os.environ["PYTHONPATH"] = root + (os.pathsep + env_path if env_path else "")
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    os.execv(str(py), [str(py), "-m", "mcp_server"])
    return 0  # pragma: no cover


if __name__ == "__main__":
    raise SystemExit(main())
