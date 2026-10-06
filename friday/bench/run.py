"""Live desktop benchmark runner.

    python -m friday.bench.run --backend legacy --model qwen2.5vl:7b-q4_K_M --reps 3 --out docs/research/bench_baseline.json

HANDS OFF the mouse and keyboard while this runs. A red banner is shown (on the second monitor
if present). Ctrl+Alt+F12 (the emergency stop) aborts the whole benchmark.
Environment (model, context, iteration cap) is fixed BEFORE friday.config is imported.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def _parse(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", choices=["legacy", "hybrid"], default="legacy")
    ap.add_argument("--model", default="qwen2.5vl:7b-q4_K_M")
    ap.add_argument("--ctx", type=int, default=32768)
    ap.add_argument("--max-iter", type=int, default=15)
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--timeout", type=int, default=100, help="seconds per run")
    ap.add_argument("--tasks", default="", help="comma list of task ids")
    ap.add_argument("--groups", default="", help="comma list of groups")
    ap.add_argument("--coord-space", default="", help="pixel|grid1000|auto (default: pixel for qwen2.5vl, else auto)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--countdown", type=int, default=12)
    ap.add_argument("--split", choices=["all", "dev", "heldout"], default="all", help="frozen task split")
    ap.add_argument("--memory", choices=["off", "on"], default="off", help="experience memory hints (Stage L)")
    ap.add_argument("--budget-minutes", type=float, default=0, help="stop starting new runs after this many minutes")
    ap.add_argument("--attended", action="store_true", help="allow approval waits (default: unattended, fail closed)")
    ap.add_argument("--list", action="store_true")
    return ap.parse_args(argv)


def _apply_env(a) -> None:
    os.environ.update({
        "MODEL": a.model, "LOCAL_MODEL": a.model, "VISION_MODEL": a.model, "CHAT_MODEL": a.model,
        "MODEL_NUM_CTX": str(a.ctx), "MAX_ITERATIONS": str(a.max_iter),
        "SHELL_TOOLS_ENABLED": "false", "OVERLAY_ENABLED": "false",
        # Never let a benchmark send screenshots to a cloud provider, even if .env has keys.
        "GEMINI_API_KEY": "", "OPENAI_API_KEY": "", "CLOUD_PROVIDER": "none",
        "MODEL_COORD_SPACE": a.coord_space or ("pixel" if a.model.startswith("qwen2.5") else "auto"),
        "FRIDAY_ESTOP": "true",
        "FRIDAY_APPROVAL_MODE": "attended" if a.attended else "unattended",
        "FRIDAY_MEMORY": "on" if a.memory == "on" else "off",
    })


class VramSampler(threading.Thread):
    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.peak = 0
        self.base = self.read()
        self._stop = threading.Event()

    @staticmethod
    def read() -> int:
        try:
            out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                                 capture_output=True, text=True, timeout=5, check=False).stdout
            return int(out.strip().splitlines()[0])
        except Exception:  # noqa: BLE001
            return 0

    def run(self) -> None:
        while not self._stop.is_set():
            self.peak = max(self.peak, self.read())
            self._stop.wait(0.5)

    def finish(self) -> int:
        self._stop.set()
        self.join(3)
        return self.peak


def _ollama_ready(model: str) -> tuple[bool, str]:
    import httpx

    try:
        tags = httpx.get("http://localhost:11434/api/tags", timeout=5).json()
    except Exception as exc:  # noqa: BLE001
        return False, f"Ollama not reachable: {exc}"
    names = {m["name"] for m in tags.get("models", [])}
    return (model in names, "ok" if model in names else f"model {model!r} not pulled; have {sorted(names)}")


BENCH_TRUSTED_TITLES = [r"^(Counter test|Name form|Submitted|Preferences|Long page|Page one|Page two|"
                        r"Canvas click|Canvas drag|Target game)\b"]


def _start_desktop_server() -> None:
    """Start Windows-MCP for a benchmark run. The explicit --backend hybrid flag is the owner's opt-in."""
    from friday.mcp_client.manager import get_mcp_manager

    mgr = get_mcp_manager()
    mgr.load()
    mgr.start("windows")
    if not mgr.wait_ready("windows", timeout=240):
        raise RuntimeError("Windows-MCP did not become ready: " + str(mgr.status()))


def _make_backend(name: str, a=None):
    if name == "legacy":
        from friday.agent.loop import run_agent

        return lambda objective, ctrl: run_agent(objective, controller=ctrl, use_overlay=False)
    from friday.agent.guard import GuardConfig
    from friday.agent.hybrid import HybridConfig, run_hybrid

    # Benchmark-only, explicit owner choices (recorded in docs/DECISIONS_NEEDED.md D-008):
    #  * the read-only Settings tasks need the default "Settings" denial lifted;
    #  * the local test pages are marked trusted so their Submit/Confirm buttons do not need a human.
    guard = GuardConfig(deny_exceptions=[r"^Settings$"], trusted_titles=BENCH_TRUSTED_TITLES)
    cfg = HybridConfig(model=a.model, num_ctx=a.ctx, max_steps=a.max_iter, guard=guard,
                       grant_issuer="benchmark-cli", coord_space=(a.coord_space or None) if a.coord_space in ("pixel", "norm1000") else None)
    return lambda objective, ctrl: run_hybrid(objective, controller=ctrl, config=cfg)


def main(argv=None) -> int:
    a = _parse(argv)
    _apply_env(a)
    from friday.bench.banner import Banner
    from friday.bench.tasks import Ctx, build_tasks, fresh_scratch, group_precondition
    from friday.bench import winutil as wu
    from friday.bench.site import Site

    tasks = build_tasks()
    if a.tasks:
        want = set(a.tasks.split(","))
        tasks = [t for t in tasks if t.id in want]
    if a.split != "all":
        from friday.bench.splits import split_of
        tasks = [t for t in tasks if split_of(t.id) == a.split]
    if a.groups:
        gs = set(a.groups.split(","))
        tasks = [t for t in tasks if t.group in gs]
    if a.list:
        for t in tasks:
            print(f"{t.group:11s} {t.id}")
        return 0

    ok, why = _ollama_ready(a.model)
    if not ok:
        print("ABORT:", why)
        return 2

    from friday.agent.runs import get_run_manager
    from friday.safety.estop import ensure_started

    es = ensure_started()
    if not es.registered:
        print("ABORT: emergency stop hotkey is not armed:", es.error)
        return 3

    out = Path(a.out)
    results: list[dict] = json.loads(out.read_text(encoding="utf-8"))["runs"] if (a.resume and out.exists()) else []
    done = {(r["task"], r["rep"]) for r in results}
    meta = {"backend": a.backend, "model": a.model, "num_ctx": a.ctx, "max_iterations": a.max_iter,
            "timeout_s": a.timeout, "reps": a.reps, "coord_space": os.environ["MODEL_COORD_SPACE"],
            "started": time.strftime("%Y-%m-%dT%H:%M:%S"), "gpu_baseline_mb": VramSampler.read()}

    def save() -> None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"meta": meta, "runs": results}, indent=1), encoding="utf-8")

    banner = Banner()
    banner.start()
    banner.set(f"FRIDAY BENCHMARK ({a.backend}, {a.model}) starts in {a.countdown}s. HANDS OFF mouse and keyboard. Stop: Ctrl+Alt+F12")
    for i in range(a.countdown, 0, -1):
        banner.set(f"FRIDAY BENCHMARK ({a.backend}, {a.model}) starts in {i}s. HANDS OFF mouse and keyboard. Stop: Ctrl+Alt+F12")
        time.sleep(1)

    site = Site()
    if a.backend == "hybrid":
        _start_desktop_server()
    backend = _make_backend(a.backend, a)
    root = Path(tempfile.mkdtemp(prefix="friday_bench_"))
    wu.show_desktop()                               # minimize everything (restored at the end)
    mgr = get_run_manager()
    aborted = False
    t_begin = time.time()
    skipped_groups: dict[str, str] = {}
    try:
        total = len(tasks) * a.reps
        n = 0
        for task in tasks:
            reason = skipped_groups.get(task.group) or group_precondition(task.group)
            if reason:
                skipped_groups[task.group] = reason
            for rep in range(1, a.reps + 1):
                n += 1
                if (task.id, rep) in done:
                    continue
                if a.budget_minutes and (time.time() - t_begin) / 60.0 > a.budget_minutes:
                    rec_nr = {"task": task.id, "group": task.group, "rep": rep, "outcome": "NOT_RUN",
                              "success": None, "failure_reason": "live-test budget exhausted"}
                    results.append(rec_nr)
                    continue
                banner.set(f"FRIDAY BENCHMARK {n}/{total}: {task.id} (rep {rep}). HANDS OFF. Stop: Ctrl+Alt+F12")
                rec = {"task": task.id, "group": task.group, "rep": rep}
                if reason:
                    rec.update(outcome="SKIPPED", failure_reason=f"precondition: {reason}", success=None)
                    results.append(rec)
                    save()
                    continue
                scratch = fresh_scratch(root, task.id, rep)
                ctx = Ctx(scratch=scratch, site=site, token=f"{task.id}-{rep}-{int(time.time())}", rep=rep)
                base_hwnds = {w.hwnd for w in wu.list_windows()}
                base_pids = {w.pid for w in wu.list_windows()}
                triggers_before = es.trigger_count
                vram = VramSampler()
                vram.start()
                t0 = time.time()
                run = None
                status, err = "error", ""
                try:
                    if task.setup:
                        task.setup(ctx)
                    objective = task.objective(ctx)
                    rec["objective"] = objective
                    run = mgr.start(objective, lambda obj, ctrl: backend(obj, ctrl), exclusive=True)
                    finished = run.wait(a.timeout)
                    if not finished:
                        mgr.cancel(run.id)
                        run.wait(15)
                        status = "timeout"
                    else:
                        status = run.status
                    err = run.error
                except Exception as exc:  # noqa: BLE001
                    err = f"{type(exc).__name__}: {exc}"
                wall = time.time() - t0
                peak = vram.finish()
                time.sleep(1.5)                      # let the UI settle before judging
                try:
                    success, why = task.check(ctx)
                except Exception as exc:  # noqa: BLE001
                    success, why = False, f"check error: {type(exc).__name__}: {exc}"
                events = list(run.events) if run else []
                actions = [e["payload"].get("step", {}).get("action") for e in events if e["type"] == "action_start"]
                steps = sum(1 for e in events if e["type"] == "action_end")
                if es.trigger_count > triggers_before:
                    status, aborted = "estop", True
                    rec["aborted"] = True
                if success:
                    failure = ""
                elif status == "timeout":
                    failure = f"timeout after {a.timeout}s; {why}"
                elif status in ("failed", "error") or err:
                    failure = f"agent {status}: {err or 'see actions'}; {why}"
                else:
                    failure = f"agent {status} but check failed: {why}"
                fail_ev = next((e["payload"] for e in reversed(events) if e["type"] == "agent_failure"), None)
                stalls = [e["payload"].get("kind") for e in events if e["type"] == "agent_stall"]
                rec.update(split=__import__("friday.bench.splits", fromlist=["x"]).split_of(task.id),
                           memory=a.memory, structured_failure=fail_ev, stalls=stalls)
                rec.update(outcome="PASS" if success else "FAIL", success=bool(success), status=status, steps=steps,
                           actions=actions[:40], wall_s=round(wall, 1), peak_vram_mb=peak,
                           failure_reason=failure, check=why)
                results.append(rec)
                save()
                print(f"[{n}/{total}] {task.id} rep{rep}: {rec['outcome']} steps={steps} {wall:.0f}s vram={peak}MB {failure[:90]}", flush=True)
                # cleanup: only windows/processes created during this run
                if ctx.chrome is not None:
                    subprocess.run(["taskkill", "/T", "/F", "/PID", str(ctx.chrome.pid)], capture_output=True, check=False)
                wu.close_new_windows(base_hwnds, base_pids)
                if aborted:
                    break
            if aborted:
                break
    finally:
        meta["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        meta["aborted_by_estop"] = aborted
        save()
        wu.show_desktop()                            # restore the user's windows
        banner.set("Friday benchmark finished.")
        time.sleep(2)
        banner.close()
        site.close()
    print(summarize(results))
    return 1 if aborted else 0


def summarize(runs: list[dict]) -> str:
    by: dict[str, list[dict]] = {}
    for r in runs:
        by.setdefault(r["task"], []).append(r)
    lines = ["| task | group | pass | steps (mean) | wall s (mean) | peak VRAM MB | top failure |", "|---|---|---|---|---|---|---|"]
    for t, rs in by.items():
        real = [r for r in rs if r["outcome"] != "SKIPPED"]
        if not real:
            lines.append(f"| {t} | {rs[0]['group']} | SKIPPED | | | | {rs[0]['failure_reason']} |")
            continue
        p = sum(1 for r in real if r["success"])
        fails = [r["failure_reason"] for r in real if not r["success"]]
        lines.append(f"| {t} | {rs[0]['group']} | {p}/{len(real)} | {statistics.mean(r['steps'] for r in real):.1f} | "
                     f"{statistics.mean(r['wall_s'] for r in real):.0f} | {max(r['peak_vram_mb'] for r in real)} | "
                     f"{(fails[0][:70] if fails else '')} |")
    real = [r for r in runs if r["outcome"] != "SKIPPED"]
    if real:
        lines.append(f"\nOverall: {sum(1 for r in real if r['success'])}/{len(real)} runs passed "
                     f"({100 * sum(1 for r in real if r['success']) / len(real):.0f}%).")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
