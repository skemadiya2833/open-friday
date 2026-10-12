"""Interactive-first resource policy and Ollama residency hints.

Does not change the Windows Ollama service. Client ``keep_alive`` values are sent
only on Friday's HTTP calls to ``OLLAMA_HOST`` (see ``friday.models.local`` and
``friday.models.manager``).

Environment knobs (owner-tunable, no service edits):
  MODEL_KEEP_ALIVE          — default chat/vision residency (often ``-1`` = until Ollama evicts)
  FRIDAY_MAIN_KEEP_ALIVE    — override for main role warmup (default: MODEL_KEEP_ALIVE)
  FRIDAY_CODER_KEEP_ALIVE   — after coder use (default ``0`` = unload immediately)
  FRIDAY_EMBED_KEEP_ALIVE   — light embed model (default ``10m``)
  FRIDAY_GPU_IDLE_UTIL_PCT  — util below this ⇒ background may use GPU (default 15)
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Literal

import httpx

from friday.config import MODEL_KEEP_ALIVE, OLLAMA_HOST, resolve_chat_model
from friday.diagnostics.hardware import hw_data_dir
from friday.models.roles import get_model_roles
from friday.perf import sample_gpu

JobClass = Literal["interactive", "background"]


def gpu_idle_threshold() -> float:
    try:
        return float(os.getenv("FRIDAY_GPU_IDLE_UTIL_PCT", "15"))
    except ValueError:
        return 15.0


def gpu_is_idle() -> bool:
    g = sample_gpu()
    util = g.util_pct
    if util is None:
        return True
    return util < gpu_idle_threshold()


def preferred_ollama_device_for(job: JobClass) -> str:
    """Advisory label for schedulers — not enforced by Ollama itself."""
    if job == "interactive":
        return "gpu"
    return "gpu" if gpu_is_idle() else "cpu"


def keep_alive_for_role(role: str) -> int | str:
    """Per-role ``keep_alive`` for Ollama API payloads."""
    if role == "coder":
        raw = os.getenv("FRIDAY_CODER_KEEP_ALIVE", "0")
    elif role == "embed":
        raw = os.getenv("FRIDAY_EMBED_KEEP_ALIVE", "10m")
    elif role in ("main", "vision", "chat", "fast"):
        raw = os.getenv("FRIDAY_MAIN_KEEP_ALIVE", MODEL_KEEP_ALIVE)
    else:
        raw = MODEL_KEEP_ALIVE
    try:
        return int(raw)
    except ValueError:
        return raw


def residency_policy_doc() -> dict[str, Any]:
    roles = get_model_roles()
    return {
        "interactive_priority": True,
        "background_on_cpu_when_gpu_busy": True,
        "gpu_idle_threshold_pct": gpu_idle_threshold(),
        "main_model": roles.main,
        "coder_model": roles.coder,
        "keep_main_warm": keep_alive_for_role("main"),
        "unload_coder_after_use": keep_alive_for_role("coder"),
        "embed_keep_alive": keep_alive_for_role("embed"),
        "note": (
            "Send keep_alive on each Ollama generate/chat/embed request; "
            "does not alter the Windows Ollama service binary or systemd/unit."
        ),
    }


def _ollama_reachable(host: str | None = None, timeout: float = 1.5) -> bool:
    base = (host or OLLAMA_HOST).rstrip("/")
    try:
        with urllib.request.urlopen(base + "/api/version", timeout=timeout) as r:  # noqa: S310
            return r.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _vram_mb() -> float | None:
    g = sample_gpu()
    return g.vram_used_mb


def _tiny_generate(host: str, model: str, keep_alive: int | str) -> dict[str, Any]:
    t0 = time.perf_counter()
    v0 = _vram_mb()
    try:
        r = httpx.post(
            f"{host.rstrip('/')}/api/generate",
            json={"model": model, "prompt": "hi", "stream": False, "keep_alive": keep_alive,
                  "options": {"num_predict": 8}},
            timeout=120.0,
        )
        r.raise_for_status()
        body = r.json()
        ok = True
        err = None
        eval_count = body.get("eval_count")
    except Exception as exc:  # noqa: BLE001
        ok = False
        err = f"{type(exc).__name__}: {exc}"
        eval_count = None
    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
    v1 = _vram_mb()
    return {
        "ok": ok,
        "error": err,
        "latency_ms": elapsed_ms,
        "eval_count": eval_count,
        "vram_before_mb": v0,
        "vram_after_mb": v1,
        "vram_delta_mb": round(v1 - v0, 2) if v0 is not None and v1 is not None else None,
    }


def measure_residency(*, write_json: bool = True) -> dict[str, Any]:
    """Measure latency/VRAM around main warm + coder unload (best-effort)."""
    host = OLLAMA_HOST.rstrip("/")
    roles = get_model_roles()
    report: dict[str, Any] = {
        "measured_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "ollama_host": host,
        "executed": False,
        "policy": residency_policy_doc(),
        "steps": [],
    }
    if not _ollama_reachable(host):
        report["status"] = "SKIPPED"
        report["reason"] = "Ollama not reachable at OLLAMA_HOST"
    else:
        report["executed"] = True
        report["status"] = "OK"
        main = roles.main or resolve_chat_model()
        coder = roles.coder
        report["steps"].append({"step": "warm_main", "model": main, **_tiny_generate(host, main, keep_alive_for_role("main"))})
        if coder and coder != main:
            report["steps"].append({"step": "touch_coder", "model": coder, **_tiny_generate(host, coder, "5m")})
            report["steps"].append(
                {"step": "unload_coder", "model": coder, **_tiny_generate(host, coder, keep_alive_for_role("coder"))}
            )
        report["steps"].append(
            {"step": "reaffirm_main", "model": main, **_tiny_generate(host, main, keep_alive_for_role("main"))}
        )

    path = hw_data_dir() / "residency.json"
    if write_json:
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    report["path"] = str(path)
    return report


def background_should_defer_to_cpu() -> bool:
    return not gpu_is_idle()
