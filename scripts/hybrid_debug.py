"""Run ONE hybrid-agent objective live and print every event (debugging aid; touches the real desktop).

    python scripts/hybrid_debug.py "Open Notepad." --max-steps 6
Keep your hands off mouse and keyboard while it runs. Ctrl+Alt+F12 stops it.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("objective")
    ap.add_argument("--model", default="qwen2.5vl:7b-q4_K_M")
    ap.add_argument("--max-steps", type=int, default=6)
    ap.add_argument("--ctx", type=int, default=32768)
    a = ap.parse_args()

    from friday.agent.control import AgentController
    from friday.agent.hybrid import HybridConfig, run_hybrid
    from friday.mcp_client.manager import get_mcp_manager
    from friday.safety.estop import ensure_started
    from friday.ui.events import current_run_id, get_bus

    ensure_started()
    m = get_mcp_manager()
    m.start("windows")
    for _ in range(90):
        if any(s.get("name") == "windows" and s.get("status") == "ready" for s in m.status()):
            break
        time.sleep(2)
    ctrl = AgentController(run_id="debug1")
    current_run_id.set("debug1")
    get_bus().subscribe_all(lambda ev: print("EV", ev.type, json.dumps(ev.payload, default=str)[:600], flush=True))
    try:
        res = run_hybrid(a.objective, controller=ctrl, config=HybridConfig(model=a.model, num_ctx=a.ctx, max_steps=a.max_steps,
                                                                          grant_issuer="debug-cli"))
        print("RESULT", res)
    finally:
        m.stop("windows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
