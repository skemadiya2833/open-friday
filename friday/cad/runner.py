"""Drive a live FreeCAD session with Taiga-S1 (socket protocol from biome-s1)."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from friday.cad.schema import Goal
from friday.cad.status import probe_status, s1_model, s1_port, s1_python, s1_repo

# Must match freecad_s1.runtime.fcenv.PROTOCOL_PREFIX (worker stdout marker).
PROTOCOL_PREFIX = "@@S1 "


@dataclass
class BuildResult:
    ok: bool
    message: str
    steps: int = 0
    iou: float | None = None
    fcstd: str | None = None
    png: str | None = None
    goal_summary: str = ""
    log: list[str] = field(default_factory=list)


class SocketEnv:
    def __init__(self, port: int, wait: float = 8.0) -> None:
        deadline = time.time() + wait
        last: OSError | None = None
        while True:
            try:
                self.sock = socket.create_connection(("127.0.0.1", port), timeout=30)
                break
            except OSError as exc:
                last = exc
                if time.time() > deadline:
                    raise RuntimeError(
                        f"FreeCAD Taiga server not reachable on 127.0.0.1:{port}. "
                        "Launch FreeCAD with scripts/freecad_gui_server.FCMacro."
                    ) from last
                time.sleep(0.5)
        self.file = self.sock.makefile("r", encoding="utf-8", newline="\n")

    def call(self, req: dict[str, Any]) -> dict[str, Any]:
        self.sock.sendall((json.dumps(req) + "\n").encode("utf-8"))
        line = self.file.readline()
        if not line:
            raise RuntimeError("FreeCAD socket closed")
        if not line.startswith(PROTOCOL_PREFIX):
            raise RuntimeError(f"unexpected FreeCAD reply: {line[:80]!r}")
        resp = json.loads(line[len(PROTOCOL_PREFIX) :])
        if not resp.get("ok"):
            raise RuntimeError(str(resp.get("error") or "FreeCAD error") + "\n" + str(resp.get("trace") or ""))
        return resp

    def close(self) -> None:
        try:
            self.file.close()
        except Exception:
            pass
        try:
            self.sock.close()
        except Exception:
            pass


def _run_inprocess(
    goal: Goal,
    *,
    out_dir: Path,
    tag: str,
    delay: float,
    on_step: Callable[[int, str], None] | None,
) -> BuildResult:
    repo = s1_repo()
    if repo is not None:
        root = str(repo.resolve())
        if root not in sys.path:
            sys.path.insert(0, root)

    from freecad_s1.model.net import from_pretrained  # type: ignore
    from freecad_s1.rollout import Policy  # type: ignore
    from freecad_s1.schema import Goal as FcGoal  # type: ignore
    from freecad_s1.schema import State  # type: ignore

    model = from_pretrained(s1_model())
    policy = Policy(model, "cpu")
    env = SocketEnv(s1_port())
    log: list[str] = []
    try:
        r = env.call({
            "op": "reset",
            "goal": goal.to_json(),
            "start": {"doc_open": True, "workbench": "PartDesignWorkbench"},
        })
        fc_goal = FcGoal.from_json(r["goal"])
        state, actions = State.from_json(r["state"]), r["actions"]
        steps = 0
        done = False
        budget = int(r.get("budget") or 200)
        while steps < budget:
            action = policy.act([state], [fc_goal], [actions])[0]
            steps += 1
            line = f"{steps:3d} {action}"
            log.append(line)
            if on_step:
                on_step(steps, action)
            s = env.call({"op": "step", "action": action})
            if s["info"].get("error"):
                log.append(f" error: {s['info']['error']}")
            if s["info"].get("done") or not s.get("expert"):
                done = bool(s["info"].get("done"))
                break
            state, actions = State.from_json(s["state"]), s["actions"]
            if delay > 0:
                time.sleep(delay)

        sc = env.call({"op": "score"})
        out_dir.mkdir(parents=True, exist_ok=True)
        saved = env.call({
            "op": "save",
            "fcstd": str(out_dir / f"{tag}.FCStd"),
            "png": str(out_dir / f"{tag}.png"),
            "background": "Current",
            "width": 1600,
            "height": 1600,
        })
        iou = float(sc.get("iou") or 0.0)
        match = bool(sc.get("match"))
        ok = bool(done and match)
        return BuildResult(
            ok=ok,
            message=("Built and matched target." if ok else f"Finished with IoU {iou:.3f}; check FreeCAD."),
            steps=steps,
            iou=iou,
            fcstd=saved.get("fcstd"),
            png=saved.get("png"),
            goal_summary=goal.summarize(),
            log=log,
        )
    finally:
        env.close()


def _sanitize_worker_noise(text: str) -> str:
    """HF Hub tqdm / auth nags must never become the spoken CAD failure line."""
    lines = []
    for line in (text or "").splitlines():
        s = line.strip()
        if not s:
            continue
        low = s.lower()
        if "fetching" in low and "files" in low:
            continue
        if "unauthenticated requests to the hf hub" in low:
            continue
        if "hf_token" in low:
            continue
        if s.startswith("\r") or "|██" in s or "|#" in s:
            continue
        lines.append(s)
    return "\n".join(lines).strip()


def _parse_worker_payload(stdout: str) -> dict[str, Any] | None:
    for line in reversed((stdout or "").splitlines()):
        s = line.strip()
        if not s.startswith("{"):
            continue
        try:
            data = json.loads(s)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and ("ok" in data or "message" in data):
            return data
    return None


def ensure_taiga_model(*, on_progress: Callable[[str], None] | None = None) -> tuple[bool, str]:
    """Download/load Taiga weights once before a build (avoids HF spam mid-build)."""
    model = s1_model()
    py = s1_python()
    repo = s1_repo()

    def log(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    log(f"Loading Taiga model ({model})…")
    env = os.environ.copy()
    env.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    env.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    if repo is not None:
        env["FREECAD_S1_REPO"] = str(repo.resolve())
        env["PYTHONPATH"] = str(repo.resolve()) + os.pathsep + env.get("PYTHONPATH", "")
    code = (
        "import os, sys\n"
        "repo = os.environ.get('FREECAD_S1_REPO','').strip()\n"
        "if repo and repo not in sys.path: sys.path.insert(0, repo)\n"
        "from freecad_s1.model.net import from_pretrained\n"
        f"from_pretrained({model!r})\n"
        "print('ok')\n"
    )
    exe = py or sys.executable
    try:
        proc = subprocess.run(
            [exe, "-c", code],
            capture_output=True,
            text=True,
            env=env,
            timeout=600,
        )
    except Exception as exc:  # noqa: BLE001
        return False, f"Taiga model load failed: {exc}"
    if proc.returncode != 0 or "ok" not in (proc.stdout or ""):
        err = _sanitize_worker_noise(proc.stderr or proc.stdout or "model load failed")
        return False, f"Taiga model load failed: {err[:400]}"
    log("Taiga model ready")
    return True, "ok"


def _run_subprocess(
    goal: Goal,
    *,
    out_dir: Path,
    tag: str,
    delay: float,
) -> BuildResult:
    worker = Path(__file__).resolve().parent / "_taiga_worker.py"
    py = s1_python() or sys.executable
    goal_path = out_dir / f"{tag}.goal.json"
    out_dir.mkdir(parents=True, exist_ok=True)
    goal_path.write_text(json.dumps(goal.to_json(), indent=2), encoding="utf-8")
    env = os.environ.copy()
    env.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    env.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    repo = s1_repo()
    if repo is not None:
        env["FREECAD_S1_REPO"] = str(repo.resolve())
        env["PYTHONPATH"] = str(repo.resolve()) + os.pathsep + env.get("PYTHONPATH", "")
    cmd = [
        py,
        str(worker),
        "--goal",
        str(goal_path),
        "--out",
        str(out_dir),
        "--tag",
        tag,
        "--model",
        s1_model(),
        "--port",
        str(s1_port()),
        "--delay",
        str(delay),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=1800)
    payload = _parse_worker_payload(proc.stdout or "")
    if payload is not None:
        return BuildResult(
            ok=bool(payload.get("ok")),
            message=str(payload.get("message") or ""),
            steps=int(payload.get("steps") or 0),
            iou=payload.get("iou"),
            fcstd=payload.get("fcstd"),
            png=payload.get("png"),
            goal_summary=goal.summarize(),
            log=list(payload.get("log") or []),
        )
    noise = _sanitize_worker_noise((proc.stderr or "") + "\n" + (proc.stdout or ""))
    return BuildResult(
        ok=False,
        message=(noise[:500] if noise else f"Taiga worker failed (exit {proc.returncode})"),
        goal_summary=goal.summarize(),
        log=(proc.stdout or "").splitlines()[-40:],
    )


def build_part(
    goal: Goal,
    *,
    out_dir: Path | None = None,
    tag: str | None = None,
    delay: float = 0.15,
    on_step: Callable[[int, str], None] | None = None,
) -> BuildResult:
    st = probe_status()
    if not st.ready_to_build:
        return BuildResult(
            ok=False,
            message="CAD build not ready: " + " ".join(st.blockers),
            goal_summary=goal.summarize(),
        )

    from friday.config import WORKSPACE_DIR

    # FreeCAD's CWD is its Program Files bin — relative paths write there and Access Denied.
    out = Path(out_dir or Path(WORKSPACE_DIR) / "cad").expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    name = tag or f"part_{int(time.time())}"

    if st.freecad_s1_importable:
        try:
            return _run_inprocess(goal, out_dir=out, tag=name, delay=delay, on_step=on_step)
        except Exception as exc:
            if not s1_python():
                return BuildResult(ok=False, message=str(exc), goal_summary=goal.summarize())
            # Fall through to worker Python
    if s1_python():
        return _run_subprocess(goal, out_dir=out, tag=name, delay=delay)
    return BuildResult(
        ok=False,
        message="freecad_s1 is not importable in this Python. Set FREECAD_S1_PYTHON to a venv that has it.",
        goal_summary=goal.summarize(),
    )
