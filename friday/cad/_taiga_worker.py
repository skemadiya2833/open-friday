"""Standalone Taiga-S1 episode worker (may run under FREECAD_S1_PYTHON).

Prints one JSON result object on the last stdout line.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
from pathlib import Path


# Must match freecad_s1.runtime.fcenv.PROTOCOL_PREFIX
PROTOCOL_PREFIX = "@@S1 "


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--goal", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--model", default="shhivv/taiga-s1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--delay", type=float, default=0.15)
    args = ap.parse_args()

    repo = os.environ.get("FREECAD_S1_REPO", "").strip()
    if repo and repo not in sys.path:
        sys.path.insert(0, repo)

    from freecad_s1.model.net import from_pretrained
    from freecad_s1.rollout import Policy
    from freecad_s1.schema import Goal, State

    goal_dict = json.loads(Path(args.goal).read_text(encoding="utf-8"))
    model = from_pretrained(args.model)
    policy = Policy(model, "cpu")

    deadline = time.time() + 30
    sock = None
    while sock is None:
        try:
            sock = socket.create_connection(("127.0.0.1", args.port), timeout=30)
        except OSError:
            if time.time() > deadline:
                print(json.dumps({"ok": False, "message": f"socket {args.port} unavailable"}))
                return 2
            time.sleep(0.5)
    assert sock is not None
    f = sock.makefile("r", encoding="utf-8", newline="\n")

    def call(req: dict) -> dict:
        sock.sendall((json.dumps(req) + "\n").encode("utf-8"))
        line = f.readline()
        if not line:
            raise RuntimeError("FreeCAD socket closed")
        if not line.startswith(PROTOCOL_PREFIX):
            raise RuntimeError(f"unexpected FreeCAD reply: {line[:80]!r}")
        resp = json.loads(line[len(PROTOCOL_PREFIX) :])
        if not resp.get("ok"):
            raise RuntimeError(str(resp.get("error") or "FreeCAD error"))
        return resp

    log: list[str] = []
    try:
        r = call({
            "op": "reset",
            "goal": goal_dict,
            "start": {"doc_open": True, "workbench": "PartDesignWorkbench"},
        })
        goal = Goal.from_json(r["goal"])
        state, actions = State.from_json(r["state"]), r["actions"]
        steps = 0
        done = False
        budget = int(r.get("budget") or 200)
        while steps < budget:
            action = policy.act([state], [goal], [actions])[0]
            steps += 1
            log.append(f"{steps:3d} {action}")
            s = call({"op": "step", "action": action})
            if s["info"].get("done") or not s.get("expert"):
                done = bool(s["info"].get("done"))
                break
            state, actions = State.from_json(s["state"]), s["actions"]
            if args.delay > 0:
                time.sleep(args.delay)
        sc = call({"op": "score"})
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        saved = call({
            "op": "save",
            "fcstd": str(out / f"{args.tag}.FCStd"),
            "png": str(out / f"{args.tag}.png"),
            "background": "Current",
            "width": 1600,
            "height": 1600,
        })
        iou = float(sc.get("iou") or 0.0)
        ok = bool(done and sc.get("match"))
        print(json.dumps({
            "ok": ok,
            "message": "Built and matched target." if ok else f"Finished with IoU {iou:.3f}.",
            "steps": steps,
            "iou": iou,
            "fcstd": saved.get("fcstd"),
            "png": saved.get("png"),
            "log": log[-40:],
        }))
        return 0 if ok else 1
    except Exception as exc:
        print(json.dumps({"ok": False, "message": str(exc), "log": log[-40:]}))
        return 2
    finally:
        try:
            f.close()
            sock.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
