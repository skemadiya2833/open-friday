# Copyright 2025 The OpenJarvis Authors
# Licensed under the Apache License, Version 2.0
# Source: open-jarvis/OpenJarvis src/openjarvis/telemetry/gpu_monitor.py
#         + energy_nvidia.py / phase_metrics.py (ideas only)
# Commit: f9e9d5d28d9e58d7fe601c331fc15a02fad32b2c
# Changes for Friday: local-only ring buffer; parse nvidia-smi (no required
# pynvml dep / no analytics clients / no network). Optional pynvml if present.

"""Local performance / energy samples for the health Performance panel."""

from __future__ import annotations

import shutil
import subprocess
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class GpuSample:
    name: str = ""
    vram_used_mb: float | None = None
    vram_total_mb: float | None = None
    power_w: float | None = None
    temp_c: float | None = None
    util_pct: float | None = None
    source: str = "none"


@dataclass
class RequestMetrics:
    kind: str  # chat | agent_run
    model: str = ""
    started_at: float = 0.0
    ended_at: float = 0.0
    ttft_ms: float | None = None
    tokens: int = 0
    tokens_per_s: float | None = None
    gpu_before: dict[str, Any] = field(default_factory=dict)
    gpu_after: dict[str, Any] = field(default_factory=dict)


_lock = threading.Lock()
_recent: deque[RequestMetrics] = deque(maxlen=40)


def _nvidia_smi() -> GpuSample:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return GpuSample(source="nvidia-smi-missing")
    try:
        out = subprocess.check_output(
            [
                exe,
                "--query-gpu=name,memory.used,memory.total,power.draw,temperature.gpu,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            timeout=3,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return GpuSample(source="nvidia-smi-error")
    lines = (out or "").strip().splitlines()
    if not lines:
        return GpuSample(source="nvidia-smi-empty")
    parts = [p.strip() for p in lines[0].split(",")]
    if len(parts) < 6:
        return GpuSample(name=parts[0] if parts else "", source="nvidia-smi-partial")

    def _f(v: str) -> float | None:
        try:
            return float(v)
        except ValueError:
            return None

    return GpuSample(
        name=parts[0],
        vram_used_mb=_f(parts[1]),
        vram_total_mb=_f(parts[2]),
        power_w=_f(parts[3]),
        temp_c=_f(parts[4]),
        util_pct=_f(parts[5]),
        source="nvidia-smi",
    )


def _try_pynvml() -> GpuSample | None:
    try:
        import pynvml  # type: ignore
    except ImportError:
        return None
    try:
        pynvml.nvmlInit()
        h = pynvml.nvmlDeviceGetHandleByIndex(0)
        name = pynvml.nvmlDeviceGetName(h)
        if isinstance(name, bytes):
            name = name.decode()
        mem = pynvml.nvmlDeviceGetMemoryInfo(h)
        power = None
        util = None
        temp = None
        try:
            power = pynvml.nvmlDeviceGetPowerUsage(h) / 1000.0
        except Exception:
            pass
        try:
            util = float(pynvml.nvmlDeviceGetUtilizationRates(h).gpu)
        except Exception:
            pass
        try:
            temp = float(pynvml.nvmlDeviceGetTemperature(h, pynvml.NVML_TEMPERATURE_GPU))
        except Exception:
            pass
        return GpuSample(
            name=str(name),
            vram_used_mb=mem.used / (1024 * 1024),
            vram_total_mb=mem.total / (1024 * 1024),
            power_w=power,
            temp_c=temp,
            util_pct=util,
            source="pynvml",
        )
    except Exception:
        return None


def sample_gpu() -> GpuSample:
    """Prefer nvidia-smi; use pynvml only if already installed (not a required dep)."""
    smi = _nvidia_smi()
    if smi.source == "nvidia-smi":
        return smi
    nv = _try_pynvml()
    return nv or smi


def record_request(metrics: RequestMetrics) -> None:
    with _lock:
        _recent.appendleft(metrics)


def start_request(kind: str, model: str = "") -> dict[str, Any]:
    return {
        "kind": kind,
        "model": model,
        "t0": time.perf_counter(),
        "ttft": None,
        "tokens": 0,
        "gpu_before": asdict(sample_gpu()),
    }


def note_first_token(ctx: dict[str, Any]) -> None:
    if ctx.get("ttft") is None:
        ctx["ttft"] = (time.perf_counter() - float(ctx["t0"])) * 1000.0


def note_token(ctx: dict[str, Any], n: int = 1) -> None:
    ctx["tokens"] = int(ctx.get("tokens") or 0) + n
    note_first_token(ctx)


def finish_request(ctx: dict[str, Any]) -> RequestMetrics:
    t1 = time.perf_counter()
    elapsed = max(1e-6, t1 - float(ctx["t0"]))
    tokens = int(ctx.get("tokens") or 0)
    m = RequestMetrics(
        kind=str(ctx.get("kind") or "chat"),
        model=str(ctx.get("model") or ""),
        started_at=time.time() - elapsed,
        ended_at=time.time(),
        ttft_ms=ctx.get("ttft"),
        tokens=tokens,
        tokens_per_s=round(tokens / elapsed, 2) if tokens else None,
        gpu_before=ctx.get("gpu_before") or {},
        gpu_after=asdict(sample_gpu()),
    )
    record_request(m)
    return m


def thermal_advice(gpu: GpuSample | None = None) -> list[str]:
    """Owner-facing hints only — no fan or power changes."""
    g = gpu or sample_gpu()
    tips: list[str] = []
    if g.temp_c is not None:
        if g.temp_c >= 85:
            tips.append("GPU ≥85°C: check case airflow; expect throttling during long agent runs.")
        elif g.temp_c >= 75:
            tips.append("GPU warm (>75°C): normal under load; avoid stacking vision + coder without unload.")
    if g.power_w is not None and g.power_w > 200:
        tips.append("High GPU draw: background tasks defer to CPU when util > FRIDAY_GPU_IDLE_UTIL_PCT.")
    if g.vram_used_mb is not None and g.vram_total_mb is not None:
        used_pct = 100.0 * g.vram_used_mb / max(g.vram_total_mb, 1)
        if used_pct > 90:
            tips.append("VRAM >90%: unload coder (keep_alive=0) before vision; see resource_policy.")
    if not tips:
        tips.append("Thermals look nominal for idle/light use.")
    return tips


def snapshot() -> dict[str, Any]:
    with _lock:
        rows = [asdict(r) for r in list(_recent)]
    gpu = sample_gpu()
    hw_summary: dict[str, Any] = {}
    try:
        from friday.diagnostics.hardware import inventory_summary_for_panel

        hw_summary = inventory_summary_for_panel()
    except Exception as exc:  # noqa: BLE001
        hw_summary = {"error": str(exc)}
    policy: dict[str, Any] = {}
    try:
        from friday.runtime.resource_policy import gpu_is_idle, residency_policy_doc

        policy = {**residency_policy_doc(), "gpu_idle_now": gpu_is_idle()}
    except Exception as exc:  # noqa: BLE001
        policy = {"error": str(exc)}
    return {
        "gpu_now": asdict(gpu),
        "hardware": hw_summary,
        "resource_policy": policy,
        "thermal_advice": thermal_advice(gpu),
        "recent": rows,
        "note": "Local only — no network telemetry. GPU via nvidia-smi (or optional pynvml if installed).",
    }
