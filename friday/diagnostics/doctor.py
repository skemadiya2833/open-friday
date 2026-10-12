"""First-run / pre-flight doctor — read-only probes, never downloads models."""

from __future__ import annotations

import importlib
import json
import os
import platform
import shutil
import socket
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from friday import __version__
from friday.config import (
    EMBED_MODEL,
    MODEL_NAME,
    OLLAMA_HOST,
    SERVER_HOST,
    SERVER_PORT,
    VISION_MODEL,
    resolve_chat_model,
)
from friday.diagnostics.hardware import collect_inventory, inventory_summary_for_panel
from friday.diagnostics.startup import validate_config


@dataclass
class Check:
    id: str
    status: str  # pass | warn | fail | skip
    message: str
    detail: dict[str, Any] = field(default_factory=dict)


_CORE_IMPORTS = ("fastapi", "uvicorn", "chromadb", "mss", "PIL", "httpx", "yaml", "pydantic")


def _tcp_open(host: str, port: int, timeout: float = 0.8) -> bool:
    h = host.strip()
    if h in ("0.0.0.0", "::", "", "*"):
        h = "127.0.0.1"
    try:
        with socket.create_connection((h, port), timeout=timeout):
            return True
    except OSError:
        return False


def _ollama_tags(timeout: float = 2.0) -> tuple[bool, list[str], str | None]:
    base = OLLAMA_HOST.rstrip("/")
    try:
        with urllib.request.urlopen(f"{base}/api/tags", timeout=timeout) as r:  # noqa: S310
            data = json.loads(r.read())
        names = [m.get("name", "") for m in (data.get("models") or []) if isinstance(m, dict)]
        return True, [n for n in names if n], None
    except urllib.error.URLError as exc:
        return False, [], f"{type(exc).__name__}: {exc.reason}"
    except Exception as exc:  # noqa: BLE001
        return False, [], f"{type(exc).__name__}: {exc}"


def _model_present(tag: str, installed: list[str]) -> bool:
    if not tag:
        return True
    base = tag.split(":")[0]
    for name in installed:
        if name == tag or name.startswith(base + ":") or name.split(":")[0] == base:
            return True
    return False


def _mcp_windows_enabled() -> bool | None:
    """Return True/False if config readable, None if unreadable."""
    try:
        import yaml

        from friday.config import MCP_CONFIG_PATH

        p = Path(MCP_CONFIG_PATH)
        if not p.is_file():
            p = Path(__file__).resolve().parent.parent.parent / "config" / "mcp_servers.yaml"
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        servers = raw.get("servers", raw)
        w = servers.get("windows") if isinstance(servers, dict) else None
        return bool(w and w.get("enabled"))
    except Exception:  # noqa: BLE001
        return None


def _check_platform() -> Check:
    system = platform.system()
    release = platform.release()
    detail = {
        "system": system,
        "release": release,
        "version": platform.version(),
        "machine": platform.machine(),
        "friday_version": __version__,
    }
    if system != "Windows":
        return Check(
            "platform",
            "fail",
            f"Friday targets Windows 11; detected {system} {release}",
            detail,
        )
    # Win11 reports release "10" with build >= 22000
    build = 0
    try:
        build = int(platform.version().split(".")[-1])
    except ValueError:
        pass
    if build and build < 22000:
        return Check(
            "platform",
            "warn",
            f"Windows build {build} looks older than Windows 11 (22000+); some features may fail",
            detail,
        )
    return Check("platform", "pass", f"Windows {release} (build {build or '?'})", detail)


def _check_python() -> Check:
    vi = sys.version_info
    detail = {
        "version": platform.python_version(),
        "executable": sys.executable,
        "bitness": 64 if sys.maxsize > 2**32 else 32,
        "prefix": sys.prefix,
        "base_prefix": getattr(sys, "base_prefix", sys.prefix),
        "in_venv": sys.prefix != getattr(sys, "base_prefix", sys.prefix),
    }
    if vi.major != 3 or vi.minor < 14:
        return Check(
            "python",
            "fail",
            f"Python 3.14+ required; found {platform.python_version()}",
            detail,
        )
    if detail["bitness"] != 64:
        return Check("python", "warn", "32-bit Python detected; use 64-bit Python 3.14", detail)
    msg = f"Python {platform.python_version()} ({detail['bitness']}-bit)"
    if detail["in_venv"]:
        msg += " in venv"
    return Check("python", "pass", msg, detail)


def _check_imports() -> Check:
    missing: list[str] = []
    for name in _CORE_IMPORTS:
        try:
            importlib.import_module(name)
        except Exception:  # noqa: BLE001
            missing.append(name)
    try:
        import friday  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        return Check("imports", "fail", f"cannot import friday: {exc}", {"missing": missing})
    if missing:
        return Check(
            "imports",
            "fail",
            f"Missing core packages: {', '.join(missing)} — pip install -r requirements/core.lock.txt",
            {"missing": missing},
        )
    return Check("imports", "pass", "Core packages importable", {"checked": list(_CORE_IMPORTS)})


def _check_voice() -> Check:
    optional = ("faster_whisper", "sounddevice", "openwakeword")
    present: list[str] = []
    absent: list[str] = []
    for name in optional:
        try:
            importlib.import_module(name)
            present.append(name)
        except Exception:  # noqa: BLE001
            absent.append(name)
    if not present:
        return Check(
            "voice",
            "skip",
            "Voice extras not installed (optional: pip install -r requirements/voice.lock.txt)",
            {"present": present, "absent": absent},
        )
    if absent:
        return Check(
            "voice",
            "warn",
            f"Partial voice extras (missing {', '.join(absent)})",
            {"present": present, "absent": absent},
        )
    return Check("voice", "pass", "Voice extras present", {"present": present})


def _check_uv() -> Check:
    path = shutil.which("uv")
    if path:
        return Check("uv", "pass", f"uv on PATH ({path})", {"path": path})
    return Check(
        "uv",
        "warn",
        "uv not on PATH — required to run Windows-MCP (hybrid desktop agent)",
        {"hint": "Install from https://docs.astral.sh/uv/ and re-open the terminal"},
    )


def _check_mcp(agent_backend: str) -> Check:
    enabled = _mcp_windows_enabled()
    detail = {"windows_enabled": enabled, "agent_backend": agent_backend}
    if enabled is None:
        return Check("mcp", "warn", "Could not read config/mcp_servers.yaml", detail)
    if agent_backend == "hybrid" and not enabled:
        return Check(
            "mcp",
            "warn",
            "AGENT_BACKEND=hybrid but windows MCP server is disabled",
            detail,
        )
    if enabled:
        return Check("mcp", "pass", "windows MCP server enabled in config", detail)
    return Check(
        "mcp",
        "pass",
        "windows MCP disabled (default) — enable in config/mcp_servers.yaml for hybrid agent",
        detail,
    )


def _check_toasts() -> Check:
    if os.name != "nt":
        return Check("toasts", "skip", "Windows toast notifications only apply on Windows")
    from friday.notify import toasts_enabled

    if toasts_enabled():
        return Check(
            "toasts",
            "pass",
            "Desktop toasts enabled (FRIDAY_TOASTS) — operators/reminders can pop on screen",
            {"enabled": True},
        )
    return Check(
        "toasts",
        "warn",
        "Desktop toasts disabled (FRIDAY_TOASTS=off)",
        {"enabled": False},
    )


def _check_camera() -> Check:
    from friday.camera.capture import opencv_available
    from friday.camera.session import camera_feature_enabled, camera_index, get_camera_session

    enabled = camera_feature_enabled()
    ocv = opencv_available()
    detail = {
        "enabled": enabled,
        "opencv": ocv,
        "index": camera_index(),
        "armed": get_camera_session().is_armed(),
    }
    if not enabled:
        return Check(
            "camera",
            "skip",
            "Camera off (default). Set FRIDAY_CAMERA=on + camera.lock.txt to enable",
            detail,
        )
    if not ocv:
        return Check(
            "camera",
            "warn",
            "FRIDAY_CAMERA=on but OpenCV missing — pip install -r requirements/camera.lock.txt",
            detail,
        )
    return Check(
        "camera",
        "pass",
        f"Camera enabled (index {camera_index()}); arm in Systems before use",
        detail,
    )


def _build_next_steps(checks: list[Check], required: dict[str, str], missing: dict[str, str]) -> list[str]:
    steps: list[str] = []
    by_id = {c.id: c for c in checks}
    if by_id.get("python", Check("", "pass", "")).status == "fail":
        steps.append("Install 64-bit Python 3.14 from https://www.python.org/downloads/ and re-run the installer.")
    if by_id.get("imports", Check("", "pass", "")).status == "fail":
        steps.append("From the Friday folder: pip install -r requirements/core.lock.txt")
    if by_id.get("ollama", Check("", "pass", "")).status == "fail":
        steps.append("Install and start Ollama from https://ollama.com/download then re-run: friday doctor")
    pull_roles: dict[str, list[str]] = {}
    for key, tag in missing.items():
        pull_roles.setdefault(tag, []).append(key)
    for tag, roles in pull_roles.items():
        steps.append(f"ollama pull {tag}   # required for {', '.join(roles)}")
    if by_id.get("uv", Check("", "pass", "")).status == "warn":
        steps.append("Install uv (https://docs.astral.sh/uv/) if you want hybrid Windows-MCP desktop control.")
    mcp = by_id.get("mcp")
    if mcp and mcp.status == "warn" and "hybrid" in mcp.message:
        steps.append("Set enabled: true under servers.windows in config/mcp_servers.yaml (or use AGENT_BACKEND=legacy).")
    if by_id.get("port_friday", Check("", "pass", "")).status == "warn":
        steps.append(f"Control Center may already be running at http://127.0.0.1:{SERVER_PORT}/")
    else:
        steps.append(f"Start Friday: friday   (then open http://127.0.0.1:{SERVER_PORT}/)")
    # de-dupe while preserving order
    seen: set[str] = set()
    out: list[str] = []
    for s in steps:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def run_doctor(*, probe_hardware: bool = True) -> dict[str, Any]:
    """Run all doctor checks. Never pulls Ollama models or installs packages."""
    checks: list[Check] = []
    checks.append(_check_platform())
    checks.append(_check_python())
    checks.append(_check_imports())

    errors = [i for i in validate_config() if i.level == "error"]
    warns = [i for i in validate_config() if i.level == "warn"]
    checks.append(
        Check(
            "config",
            "fail" if errors else ("warn" if warns else "pass"),
            f"{len(errors)} error(s), {len(warns)} warning(s) from validate_config",
            {"errors": [str(i) for i in errors], "warnings": [str(i) for i in warns]},
        )
    )

    inv_summary: dict[str, Any] = {}
    if probe_hardware:
        try:
            inv = collect_inventory()
            inv_summary = inventory_summary_for_panel(inv)
            gpu = inv_summary.get("gpu_name")
            checks.append(
                Check(
                    "gpu",
                    "pass" if gpu else "warn",
                    gpu
                    or "No NVIDIA GPU detected via nvidia-smi (local VL may be CPU-only or Ollama uses another backend)",
                    inv_summary,
                )
            )
        except Exception as exc:  # noqa: BLE001
            checks.append(Check("gpu", "skip", f"hardware probe failed: {exc}"))

    up, models, err = _ollama_tags()
    checks.append(
        Check(
            "ollama",
            "pass" if up else "fail",
            "Ollama reachable" if up else f"Ollama not reachable at {OLLAMA_HOST}",
            {"error": err, "model_count": len(models)},
        )
    )

    required = {
        "chat": resolve_chat_model(),
        "vision": VISION_MODEL or MODEL_NAME,
        "embed": EMBED_MODEL,
    }
    missing = {k: v for k, v in required.items() if v and up and not _model_present(v, models)}
    checks.append(
        Check(
            "models",
            "pass" if up and not missing else ("warn" if up else "skip"),
            "Required models present"
            if not missing
            else f"Missing: {', '.join(f'{k}={v}' for k, v in missing.items())}",
            {
                "required": required,
                "installed_sample": models[:12],
                "missing": missing,
                "pull_hint": "Run `ollama pull <name>` yourself — doctor never downloads.",
            },
        )
    )

    port_busy = _tcp_open("127.0.0.1", SERVER_PORT)
    checks.append(
        Check(
            "port_friday",
            "warn" if port_busy else "pass",
            f"TCP {SERVER_PORT} already open on loopback (Friday may already be running)"
            if port_busy
            else f"TCP {SERVER_PORT} free on loopback",
            {"host": SERVER_HOST, "port": SERVER_PORT},
        )
    )

    ollama_port = 11434
    try:
        from urllib.parse import urlparse

        ollama_port = urlparse(OLLAMA_HOST).port or 11434
    except Exception:  # noqa: BLE001
        pass
    ollama_listen = _tcp_open("127.0.0.1", ollama_port)
    checks.append(
        Check(
            "port_ollama",
            "pass" if ollama_listen else "warn",
            f"Ollama port {ollama_port} accepting connections"
            if ollama_listen
            else f"Nothing listening on {ollama_port}",
        )
    )

    checks.append(_check_uv())
    agent_backend = os.getenv("AGENT_BACKEND", "legacy").strip().lower() or "legacy"
    checks.append(_check_mcp(agent_backend))
    checks.append(_check_voice())
    checks.append(_check_toasts())
    checks.append(_check_camera())

    next_steps = _build_next_steps(checks, required, missing if up else dict(required))

    status_order = {"fail": 0, "warn": 1, "skip": 2, "pass": 3}
    worst = min((status_order.get(c.status, 9) for c in checks), default=3)
    overall = {0: "fail", 1: "warn", 2: "skip", 3: "pass"}.get(worst, "warn")

    return {
        "ok": overall == "pass",
        "status": overall,
        "version": __version__,
        "checks": [{"id": c.id, "status": c.status, "message": c.message, "detail": c.detail} for c in checks],
        "next_steps": next_steps,
        "hardware": inv_summary,
    }


def print_doctor_report(report: dict[str, Any] | None = None) -> int:
    """Print human-readable doctor output; return exit code (0=pass, 1=warn, 2=fail)."""
    report = report or run_doctor()
    status = report.get("status", "warn")
    ver = report.get("version", "")
    print(f"[Friday doctor] overall: {status.upper()}" + (f"  (v{ver})" if ver else ""))
    for c in report.get("checks") or []:
        mark = {"pass": "OK", "warn": "WARN", "fail": "FAIL", "skip": "SKIP"}.get(c["status"], "?")
        print(f"  [{mark}] {c['id']}: {c['message']}")
    steps = report.get("next_steps") or []
    if steps:
        print("[Friday doctor] next steps:")
        for s in steps:
            print(f"  -> {s}")
    codes = {"pass": 0, "warn": 1, "fail": 2, "skip": 1}
    return codes.get(status, 1)
