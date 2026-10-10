"""15-minute live legacy vs hybrid comparison on five simple tasks (3 reps).

Scratch only. Prefers tools-first/direct actions; falls back to a short agent run.
E-stop: Ctrl+Alt+F12. Writes docs/research/backend_live_stu.json.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _run_one(backend: str, objective: str, scratch: Path, per_task_s: float = 40.0) -> dict:
    from friday.agent import router as RT
    from friday.types import AgentStatus

    t0 = time.monotonic()
    routed = RT.route(objective, workspace=str(scratch))
    if routed.handled:
        return {
            "path": "direct",
            "status": "PASS" if routed.ok else "FAIL",
            "detail": routed.message[:160],
            "elapsed_s": round(time.monotonic() - t0, 2),
        }

    box: dict = {"status": "TIMEOUT", "detail": ""}

    def _agent():
        try:
            if backend == "hybrid":
                from friday.agent.control import AgentController
                from friday.agent.hybrid import HybridConfig, run_hybrid

                st = run_hybrid(
                    objective,
                    controller=AgentController(),
                    config=HybridConfig(
                        max_steps=6,
                        settle_seconds=0.35,
                        model_timeout=20,
                        tools_first=False,
                    ),
                )
                box["status"] = "PASS" if st == AgentStatus.COMPLETED else str(getattr(st, "name", st))
            else:
                from friday.agent.runs import get_run_manager

                run = get_run_manager().start(objective, exclusive=True)
                deadline = time.monotonic() + per_task_s
                while time.monotonic() < deadline:
                    st = (run.status or "").lower()
                    if st in {"completed", "success", "failed", "cancelled", "error"}:
                        box["status"] = "PASS" if st in {"completed", "success"} else st.upper()
                        break
                    time.sleep(0.4)
                else:
                    box["status"] = "TIMEOUT"
                try:
                    get_run_manager().cancel(run.id)
                except Exception:
                    pass
        except Exception as exc:  # noqa: BLE001
            box["status"] = "ERROR"
            box["detail"] = str(exc)[:200]

    th = threading.Thread(target=_agent, daemon=True)
    th.start()
    th.join(per_task_s + 5)
    if th.is_alive():
        box["status"] = "TIMEOUT"
    box["elapsed_s"] = round(time.monotonic() - t0, 2)
    box["path"] = "agent"
    return box


def main() -> int:
    os.environ.setdefault("FRIDAY_AUTH", "off")
    os.environ["OVERLAY_ENABLED"] = "false"
    os.environ["SHELL_TOOLS_ENABLED"] = "false"
    os.environ["FRIDAY_TOOLS_FIRST"] = "true"
    budget = 15 * 60
    t_end = time.monotonic() + budget
    scratch = Path(tempfile.mkdtemp(prefix="friday_stu_"))
    results = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "scratch": str(scratch),
        "budget_s": budget,
        "backends": {},
    }
    for backend in ("legacy", "hybrid"):
        os.environ["AGENT_BACKEND"] = backend
        rows = []
        for name in ("open_notepad", "type_save", "calculator", "settings", "open_folder"):
            for rep in range(1, 4):
                if time.monotonic() >= t_end:
                    rows.append({"task": name, "rep": rep, "status": "SKIPPED_BUDGET"})
                    break
                note = scratch / f"two_lines_{backend}_{rep}.txt"
                objectives = {
                    "open_notepad": "Open Notepad",
                    "type_save": (
                        f"Open Notepad, type the word alpha, press Enter, type the word beta, "
                        f"and save the file as {note}"
                    ),
                    "calculator": "Open Calculator",
                    "settings": "Open Settings",
                    "open_folder": f"Open the folder {scratch}",
                }
                objective = objectives[name]
                row = _run_one(backend, objective, scratch, per_task_s=35.0)
                row.update({"task": name, "rep": rep})
                rows.append(row)
                print(f"[{backend}] {name}#{rep}: {row['status']} via {row.get('path')} ({row.get('elapsed_s')}s)")
        passed = sum(1 for r in rows if str(r.get("status", "")).upper() in {"PASS", "COMPLETED"})
        results["backends"][backend] = {"rows": rows, "passed": passed, "total": len(rows)}

    leg = results["backends"].get("legacy", {}).get("passed", 0)
    hyb = results["backends"].get("hybrid", {}).get("passed", 0)
    results["recommend_default"] = "hybrid" if hyb > leg else "legacy"
    results["wall_s"] = round(budget - max(0.0, t_end - time.monotonic()), 1)
    out = ROOT / "docs" / "research" / "backend_live_stu.json"
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps({"legacy_passed": leg, "hybrid_passed": hyb, "recommend": results["recommend_default"]}, indent=2))
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
