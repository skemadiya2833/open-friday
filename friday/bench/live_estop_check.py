"""Live check: the emergency-stop hotkey halts the REAL vision loop (Ollama + executor).

Runs a harmless endless objective (Calculator only), injects Ctrl+Alt+F12 after the agent has
acted at least once, and measures halt latency. HANDS OFF mouse and keyboard while it runs.
    python -m friday.bench.live_estop_check [--model qwen2.5vl:7b-q4_K_M]
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="qwen2.5vl:7b-q4_K_M")
    ap.add_argument("--out", default="docs/research/live_estop_check.json")
    a = ap.parse_args()
    os.environ.update({"MODEL": a.model, "LOCAL_MODEL": a.model, "VISION_MODEL": a.model, "CHAT_MODEL": a.model,
                       "MODEL_NUM_CTX": "32768", "MAX_ITERATIONS": "200", "SHELL_TOOLS_ENABLED": "false",
                       "OVERLAY_ENABLED": "false", "GEMINI_API_KEY": "", "OPENAI_API_KEY": "", "CLOUD_PROVIDER": "none",
                       "MODEL_COORD_SPACE": "pixel", "FRIDAY_ESTOP": "true"})
    from friday.agent.loop import run_agent
    from friday.agent.runs import get_run_manager
    from friday.bench import winutil as wu
    from friday.bench.banner import Banner
    from friday.safety.estop import ensure_started

    es = ensure_started()
    if not es.registered:
        print("ABORT: hotkey not armed:", es.error)
        return 3
    banner = Banner()
    banner.start()
    for i in range(8, 0, -1):
        banner.set(f"ESTOP LIVE CHECK in {i}s. HANDS OFF mouse and keyboard.")
        time.sleep(1)
    base = {w.hwnd for w in wu.list_windows()}
    pids = {w.pid for w in wu.list_windows()}
    wu.show_desktop()
    mgr = get_run_manager()
    run = mgr.start("Open the Calculator app and keep typing 1 + 1 = over and over. Never stop.",
                    lambda obj, ctrl: run_agent(obj, controller=ctrl, use_overlay=False))
    t_end = time.time() + 150
    while time.time() < t_end and not any(e["type"] == "action_end" for e in run.events):
        time.sleep(0.5)
    acted = sum(1 for e in run.events if e["type"] == "action_end")
    banner.set("ESTOP LIVE CHECK: pressing Ctrl+Alt+F12 now")
    u = ctypes.windll.user32
    t0 = time.time()
    for vk in (0x11, 0x12, 0x7B):
        u.keybd_event(vk, 0, 0, 0)
        time.sleep(0.03)
    for vk in (0x7B, 0x12, 0x11):
        u.keybd_event(vk, 0, 2, 0)
        time.sleep(0.03)
    halted = run.wait(30)
    latency = round(time.time() - t0, 2)
    res = {"model": a.model, "actions_before_stop": acted, "halted": halted, "status": run.status,
           "halt_latency_s": latency, "hotkey_triggers": es.trigger_count, "events": len(run.events)}
    print(json.dumps(res, indent=2))
    time.sleep(1)
    wu.close_new_windows(base, pids)
    wu.show_desktop()
    banner.close()
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(res, indent=2), encoding="utf-8")
    return 0 if (halted and acted >= 1 and es.trigger_count == 1) else 1


if __name__ == "__main__":
    raise SystemExit(main())
