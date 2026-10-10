"""H3: VRAM with Whisper large-v3-turbo float16 resident next to an agent LLM during a REAL agent run.

    python scripts/vram_coload.py [--models qwen2.5vl:7b-q4_K_M,qwen3.5:9b] [--ctx 32768]

For each model: STT stays loaded; the hybrid agent runs "Open Notepad." (one launch, then done) while a thread samples
nvidia-smi; `ollama ps` shows whether Ollama split the model between GPU and CPU. Finally the cost of a model swap
(unload + cold reload through ModelManager) is timed. Result: docs/research/vram_coload.json. Touches only Notepad
windows it opened itself (closed afterwards). Ctrl+Alt+F12 aborts.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def used_mb() -> int:
    out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
                         capture_output=True, text=True, timeout=10).stdout.strip().splitlines()[0]
    return int(out.split(",")[0])


def total_mb() -> int:
    out = subprocess.run(["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                         capture_output=True, text=True, timeout=10).stdout.strip().splitlines()[0]
    return int(out)


def ollama_ps() -> list[dict]:
    import httpx

    return [{"name": m["name"], "size_mb": m["size"] // 2**20, "size_vram_mb": m.get("size_vram", 0) // 2**20,
             "context": m.get("context_length")} for m in httpx.get("http://localhost:11434/api/ps", timeout=10).json().get("models", [])]


def unload_all() -> None:
    import httpx

    for m in ollama_ps():
        httpx.post("http://localhost:11434/api/generate", json={"model": m["name"], "prompt": "", "keep_alive": 0}, timeout=60)
    time.sleep(2)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="qwen2.5vl:7b-q4_K_M,qwen3.5:9b")
    ap.add_argument("--ctx", type=int, default=32768)
    a = ap.parse_args()

    from friday.agent.control import AgentController
    from friday.agent.hybrid import HybridConfig, run_hybrid
    from friday.bench import winutil as wu
    from friday.mcp_client.manager import get_mcp_manager
    from friday.safety.estop import ensure_started
    from friday.ui.events import current_run_id

    unload_all()
    res: dict = {"total_mb": total_mb(), "baseline_mb": used_mb(), "stt": "large-v3-turbo float16", "runs": []}
    es = ensure_started()
    before = es.trigger_count

    t0 = time.time()
    from friday.voice import stt
    stt.VOICE_STT_MODEL = "large-v3-turbo"
    model = stt._get_model()
    res["stt_load_s"] = round(time.time() - t0, 1)
    res["after_stt_mb"] = used_mb()
    res["stt_loaded"] = model is not None

    m = get_mcp_manager()
    m.start("windows")
    for _ in range(45):
        if any(s.get("name") == "windows" and s.get("status") == "ready" for s in m.status()):
            break
        time.sleep(2)
    for name in a.models.split(","):
        peak = [0]
        stop = threading.Event()

        def sample() -> None:
            while not stop.is_set():
                peak[0] = max(peak[0], used_mb())
                time.sleep(0.5)
        th = threading.Thread(target=sample, daemon=True)
        base_hw = {w.hwnd for w in wu.list_windows()}
        base_pid = {w.pid for w in wu.list_windows()}
        th.start()
        ctrl = AgentController(run_id=f"vram-{name}")
        current_run_id.set(ctrl.run_id)
        t1 = time.time()
        try:
            status = run_hybrid("Open Notepad.", controller=ctrl,
                                config=HybridConfig(model=name, num_ctx=a.ctx, max_steps=6, grant_issuer="vram-coload"))
        finally:
            stop.set()
            th.join(2)
        ps = ollama_ps()
        res["runs"].append({"model": name, "status": str(status), "wall_s": round(time.time() - t1, 1), "peak_mb": peak[0],
                            "ollama_ps": ps, "fits_fully_on_gpu": all(p["size_vram_mb"] >= p["size_mb"] - 8 for p in ps),
                            "headroom_mb": res["total_mb"] - peak[0]})
        wu.close_new_windows(base_hw, base_pid)
        unload_all()
    # swap cost with STT still resident: cold load of each model
    swap = {}
    from friday.models.manager import get_model_manager
    import httpx
    for name in a.models.split(","):
        t2 = time.time()
        httpx.post("http://localhost:11434/api/generate", json={"model": name, "prompt": "", "keep_alive": "2m",
                                                                "options": {"num_ctx": a.ctx}}, timeout=300)
        swap[name] = {"cold_load_s": round(time.time() - t2, 1), "used_mb": used_mb()}
        t3 = time.time()
        get_model_manager()._unload(name)
        swap[name]["unload_s"] = round(time.time() - t3, 1)
    res["swap"] = swap
    res["estop"] = es.trigger_count > before
    m.stop("windows")
    (ROOT / "docs" / "research" / "vram_coload.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps(res, indent=1))
    import os
    os._exit(0)


if __name__ == "__main__":
    raise SystemExit(main())
