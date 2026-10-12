"""First-run / pre-flight doctor — read-only probes, never downloads models."""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from friday.config import (
    EMBED_MODEL,
    MODEL_NAME,
    OLLAMA_HOST,
    SERVER_HOST,
    SERVER_PORT,
    VISION_MODEL,
    resolve_chat_model,
)
from friday.diagnostics.startup import validate_config
from friday.diagnostics.hardware import collect_inventory, inventory_summary_for_panel


@dataclass
class Check:
    id: str
    status: str  # pass | warn | fail | skip
    message: str
    detail: dict[str, Any] = field(default_factory=dict)


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


def run_doctor(*, probe_hardware: bool = True) -> dict[str, Any]:
    """Run all doctor checks. Never pulls Ollama models or installs packages."""
    checks: list[Check] = []
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
                    gpu or "No NVIDIA GPU detected via nvidia-smi (local VL may be CPU-only or Ollama uses another backend)",
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
            "Required models present" if not missing else f"Missing: {', '.join(f'{k}={v}' for k, v in missing.items())}",
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
            f"Ollama port {ollama_port} accepting connections" if ollama_listen else f"Nothing listening on {ollama_port}",
        )
    )

    status_order = {"fail": 0, "warn": 1, "skip": 2, "pass": 3}
    worst = min((status_order.get(c.status, 9) for c in checks), default=3)
    overall = {0: "fail", 1: "warn", 2: "skip", 3: "pass"}.get(worst, "warn")

    return {
        "ok": overall == "pass",
        "status": overall,
        "checks": [{"id": c.id, "status": c.status, "message": c.message, "detail": c.detail} for c in checks],
        "hardware": inv_summary,
    }


def print_doctor_report(report: dict[str, Any] | None = None) -> int:
    """Print human-readable doctor output; return exit code (0=pass, 1=warn, 2=fail)."""
    report = report or run_doctor()
    status = report.get("status", "warn")
    print(f"[Friday doctor] overall: {status.upper()}")
    for c in report.get("checks") or []:
        mark = {"pass": "OK", "warn": "WARN", "fail": "FAIL", "skip": "SKIP"}.get(c["status"], "?")
        print(f"  [{mark}] {c['id']}: {c['message']}")
    codes = {"pass": 0, "warn": 1, "fail": 2, "skip": 1}
    return codes.get(status, 1)
