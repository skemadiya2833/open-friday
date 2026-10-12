"""Stage 3 measured experiments — writes JSON under ``.internal/hw/`` only."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import httpx
import numpy as np

from friday.config import EMBED_MODEL, OLLAMA_HOST
from friday.diagnostics.hardware import collect_inventory, hw_data_dir
from friday.perf import sample_gpu


def _write_json(name: str, payload: dict[str, Any]) -> Path:
    path = hw_data_dir() / name
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def measure_speech_and_embed(*, audio_seconds: float = 2.0) -> dict[str, Any]:
    """Compare Whisper small (CPU) vs large-v3-turbo (GPU) and Ollama embeddings timing."""
    report: dict[str, Any] = {
        "measured_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "executed": False,
        "whisper": [],
        "embeddings": {},
    }
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        report["status"] = "SKIPPED"
        report["reason"] = "faster-whisper not installed in this environment"
        _write_json("speech_embed.json", report)
        return report

    # Synthetic speech-like audio (no downloads): quiet noise burst — timing only.
    sr = 16000
    n = int(sr * audio_seconds)
    rng = np.random.default_rng(42)
    audio = (rng.standard_normal(n).astype(np.float32) * 0.02)

    from faster_whisper import WhisperModel

    configs = [
        ("small", "cpu", "int8"),
        ("large-v3-turbo", "cuda", "float16"),
        ("large-v3-turbo", "cpu", "int8"),
    ]
    for model_name, device, compute in configs:
        row: dict[str, Any] = {"model": model_name, "device": device, "compute_type": compute}
        v0 = sample_gpu().vram_used_mb
        t0 = time.perf_counter()
        try:
            wm = WhisperModel(model_name, device=device, compute_type=compute)
            load_s = time.perf_counter() - t0
            t1 = time.perf_counter()
            segments, _info = wm.transcribe(audio, language="en", beam_size=1, vad_filter=False)
            _ = list(segments)
            infer_s = time.perf_counter() - t1
            row.update({"status": "OK", "load_s": round(load_s, 3), "infer_s": round(infer_s, 3)})
        except Exception as exc:  # noqa: BLE001
            row.update({"status": "FAILED", "error": f"{type(exc).__name__}: {exc}"})
        row["vram_after_mb"] = sample_gpu().vram_used_mb
        row["vram_delta_mb"] = (
            round(row["vram_after_mb"] - v0, 2) if v0 is not None and row["vram_after_mb"] is not None else None
        )
        report["whisper"].append(row)

    host = OLLAMA_HOST.rstrip("/")
    emb: dict[str, Any] = {"model": EMBED_MODEL, "host": host}
    try:
        with urllib.request.urlopen(host + "/api/version", timeout=2.0) as r:  # noqa: S310
            if r.status != 200:
                raise urllib.error.URLError("bad status")
        t0 = time.perf_counter()
        resp = httpx.post(
            f"{host}/api/embeddings",
            json={"model": EMBED_MODEL, "prompt": "hardware inventory probe"},
            timeout=60.0,
        )
        resp.raise_for_status()
        emb.update(
            {
                "status": "OK",
                "latency_ms": round((time.perf_counter() - t0) * 1000.0, 2),
                "dim": len(resp.json().get("embedding") or []),
            }
        )
    except Exception as exc:  # noqa: BLE001
        emb.update({"status": "SKIPPED", "error": f"{type(exc).__name__}: {exc}"})

    report["embeddings"] = emb
    report["executed"] = True
    report["status"] = "OK"
    _write_json("speech_embed.json", report)
    return report


def _find_ollama_exe() -> str | None:
    exe = shutil.which("ollama")
    if exe:
        return exe
    for candidate in (
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
        Path("C:/Program Files/Ollama/ollama.exe"),
    ):
        if candidate.is_file():
            return str(candidate)
    return None


def measure_ollama_tune(*, port: int = 11435, num_predict: int = 16) -> dict[str, Any]:
    """Spawn temporary second Ollama on loopback; never touches Windows service."""
    report: dict[str, Any] = {
        "measured_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "port": port,
        "executed": False,
        "env_attempted": {
            "OLLAMA_FLASH_ATTENTION": "1",
            "OLLAMA_KV_CACHE_TYPE": "q8_0",
        },
    }
    exe = _find_ollama_exe()
    if not exe:
        report["status"] = "BLOCKED"
        report["reason"] = "ollama executable not found on PATH"
        _write_json("ollama_tune.json", report)
        return report

    host = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    env["OLLAMA_HOST"] = f"127.0.0.1:{port}"
    env["OLLAMA_FLASH_ATTENTION"] = "1"
    env["OLLAMA_KV_CACHE_TYPE"] = "q8_0"

    proc: subprocess.Popen[str] | None = None
    try:
        proc = subprocess.Popen(
            [exe, "serve"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        deadline = time.time() + 25.0
        up = False
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(host + "/api/version", timeout=1.0) as r:  # noqa: S310
                    up = r.status == 200
                    if up:
                        break
            except (urllib.error.URLError, TimeoutError, OSError):
                time.sleep(0.4)
        if not up:
            err = (proc.stderr.read(4000) if proc.stderr else "") if proc.poll() is not None else "timeout waiting for port"
            report["status"] = "BLOCKED"
            report["reason"] = f"temporary ollama did not become ready: {err}"
            _write_json("ollama_tune.json", report)
            return report

        tags = httpx.get(f"{host}/api/tags", timeout=10.0).json().get("models") or []
        names = [m.get("name") for m in tags if m.get("name")]
        if not names:
            report["status"] = "BLOCKED"
            report["reason"] = "no models listed on temporary instance (OLLAMA_MODELS may differ)"
        else:
            # Prefer smallest tag for a quick probe (avoid loading 30B on cold second server).
            def _size_key(tag: str) -> tuple[int, str]:
                t = tag.lower()
                for token, score in ((":1b", 1), (":3b", 3), (":4b", 4), (":7b", 7), (":8b", 8), (":9b", 9)):
                    if token in t:
                        return (score, tag)
                return (999, tag)

            model = sorted(names, key=_size_key)[0]
            v0 = sample_gpu().vram_used_mb
            t0 = time.perf_counter()
            gen = httpx.post(
                f"{host}/api/generate",
                json={"model": model, "prompt": "Say OK.", "stream": False, "options": {"num_predict": num_predict}},
                timeout=300.0,
            )
            gen.raise_for_status()
            body = gen.json()
            report.update(
                {
                    "status": "OK",
                    "executed": True,
                    "model": model,
                    "latency_ms": round((time.perf_counter() - t0) * 1000.0, 2),
                    "eval_count": body.get("eval_count"),
                    "vram_before_mb": v0,
                    "vram_after_mb": sample_gpu().vram_used_mb,
                }
            )
    except Exception as exc:  # noqa: BLE001
        report["status"] = "BLOCKED"
        detail = f"{type(exc).__name__}: {exc}"
        if proc and proc.stderr:
            try:
                err_tail = proc.stderr.read(2000)
                if err_tail:
                    detail += f" | stderr: {err_tail.strip()[:500]}"
            except Exception:
                pass
        report["reason"] = detail + " (second instance may contend with primary Ollama on GPU)"
    finally:
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()

    _write_json("ollama_tune.json", report)
    return report


def write_igpu_display_guide() -> Path:
    inv = collect_inventory()
    layout = inv.get("gpu_layout") or {}
    lines = [
        "# iGPU display handoff (research only — no changes made)",
        "",
        f"Collected: {inv.get('collected_at', 'unknown')}",
        "",
        "## What WMI reports now",
        "",
        f"- **Active display adapter(s):** {', '.join(layout.get('display_active_on') or []) or 'unknown'}",
        f"- **Idle dGPU VRAM used (MB):** {layout.get('idle_discrete_vram_used_mb')}",
        "",
        "### Video controllers",
        "",
    ]
    for vc in layout.get("wmi_all") or []:
        if not isinstance(vc, dict):
            continue
        lines.append(f"- **{vc.get('name')}** — resolution `{vc.get('current_resolution')}` — PNP `{vc.get('pnp_device_id')}`")
    lines.extend(
        [
            "",
            "## Owner steps to move monitors to iGPU (Windows 11)",
            "",
            "1. Open **Settings → System → Display → Advanced display**.",
            "2. For each monitor, open **Display adapter properties** and note which GPU drives it today.",
            "3. If the NVIDIA GPU is driving desktop compositing, open **NVIDIA Control Panel → System → Display** "
            "(or **Set up multiple displays**) and ensure monitors are attached to the **AMD Radeon (8700G)** ports, "
            "not the RTX, then reboot if ports were changed physically.",
            "4. Alternative path: **Settings → System → Display → Graphics** — set global preference to power-saving "
            "for desktop apps only after cables are on iGPU outputs (Friday/VLM still uses dGPU via CUDA).",
            "5. After switch, expect **lower idle VRAM** on the RTX (no desktop framebuffer). Re-run inventory via "
            "`python scripts/hw_stage3_run.py` and compare `idle_discrete_vram_used_mb`.",
            "",
            "## Risks",
            "",
            "- BIOS must enable iGPU multi-monitor if ports are on the motherboard.",
            "- HDMI/DP on the RTX cannot be reassigned to iGPU in software alone — cable routing matters.",
            "- Do not disable the RTX in Device Manager; Ollama/CUDA needs it.",
            "",
        ]
    )
    path = hw_data_dir() / "igpu_display.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_npu_research_md(*, web_notes: str | None = None) -> Path:
    lines = [
        "# Ryzen 7 8700G NPU — whisper.cpp / Ryzen AI (research only)",
        "",
        "## Local repo notes",
        "",
        "- Skip NPU for LLM/Whisper on this stack; discrete GPU is faster; "
        "8700G NPU aimed at vision preprocessing per AMD forum/issue #122 on gaia.",
        "- Friday runs Python 3.14; Ryzen AI ONNX stack historically targets 3.10–3.12 (would need an isolated worker).",
        "",
        "## Web confirmation (not installed here)",
        "",
        web_notes
        or (
            "- AMD Ryzen AI docs: whisper.cpp NPU offload targets **Ryzen AI 300 series** (Strix), Windows-only today.\n"
            "- 8700G lists 16 TOPS but is Phoenix — use CPU/iGPU/dGPU for Whisper; skip Ryzen AI Software install for Friday.\n"
            "- Sources: https://ryzenai.docs.amd.com/en/latest/whisper_cpp.html , "
            "https://github.com/lemonade-sdk/whisper.cpp-rocm (NPU table: Strix only)."
        ),
        "",
        "## Recommendation for Friday Stage 3",
        "",
        "**Skip Ryzen AI install** for whisper.cpp/STT. Use RTX + faster-whisper (already integrated) or CPU small model "
        "for background. Revisit only if AMD documents 8700G whisper.cpp NPU backends with stable Windows drivers and "
        "a clear perf win over RTX 5060 Ti for your clip lengths.",
        "",
    ]
    path = hw_data_dir() / "npu_research.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def run_all_experiments(*, include_heavy_whisper: bool = True) -> dict[str, str]:
    """Run inventory + experiments; returns paths written."""
    out: dict[str, str] = {}
    collect_inventory(write_json=True)
    out["inventory.json"] = str(hw_data_dir() / "inventory.json")

    from friday.runtime.resource_policy import measure_residency

    out["residency.json"] = str(measure_residency().get("path", hw_data_dir() / "residency.json"))

    if include_heavy_whisper:
        measure_speech_and_embed(audio_seconds=1.5)
    else:
        r = {"status": "SKIPPED", "reason": "include_heavy_whisper=false"}
        _write_json("speech_embed.json", r)
    out["speech_embed.json"] = str(hw_data_dir() / "speech_embed.json")

    measure_ollama_tune()
    out["ollama_tune.json"] = str(hw_data_dir() / "ollama_tune.json")

    out["igpu_display.md"] = str(write_igpu_display_guide())
    out["npu_research.md"] = str(write_npu_research_md())
    return out
