"""Measure heuristic complexity routing on the 20-prompt persona set.

Default mode: blend existing docs/research/fast_brain_bench.json rows by
score_complexity (no new Ollama calls). Pass --live to call models.

Writes docs/research/complexity_routing_bench.json.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from friday.models.complexity import score_complexity, select_chat_role  # noqa: E402
from scripts.eval_persona import PROMPTS  # noqa: E402


def blend_from_prior() -> dict:
    prior = json.loads((ROOT / "docs/research/fast_brain_bench.json").read_text(encoding="utf-8"))
    by4 = {r["id"]: r for r in prior["fast_4b"]["rows"]}
    by9 = {r["id"]: r for r in prior["main_9b"]["rows"]}
    rows = []
    for p in PROMPTS:
        role = select_chat_role(p["text"])
        src = by4[p["id"]] if role == "fast" else by9[p["id"]]
        scored = score_complexity(p["text"])
        rows.append({
            "id": p["id"],
            "role": role,
            "complexity_score": scored.score,
            "tier": scored.tier,
            "elapsed_s": src["elapsed_s"],
            "correctness": src["correctness"],
            "persona": src["persona"],
            "reply": src.get("reply", "")[:200],
        })
    n = max(1, len(rows))
    always9 = prior["main_9b"]
    routed = {
        "n": len(rows),
        "avg_latency_s": round(sum(r["elapsed_s"] for r in rows) / n, 3),
        "avg_correctness": round(sum(r["correctness"] for r in rows) / n, 3),
        "avg_persona": round(sum(r["persona"] for r in rows) / n, 3),
        "n_fast": sum(1 for r in rows if r["role"] == "fast"),
        "n_main": sum(1 for r in rows if r["role"] == "main"),
        "rows": rows,
    }
    favor = (
        routed["avg_correctness"] >= always9["avg_correctness"]
        and routed["avg_latency_s"] < always9["avg_latency_s"] * 0.85
        and routed["avg_persona"] >= 0.95
    )
    return {
        "mode": "blend_prior_fast_brain_bench",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "always_9b": {
            "avg_latency_s": always9["avg_latency_s"],
            "avg_correctness": always9["avg_correctness"],
            "avg_persona": always9["avg_persona"],
        },
        "routed": routed,
        "recommend_enable_by_default": favor,
        "keep_9b_default": not favor,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="Call Ollama (slow)")
    args = ap.parse_args()
    if args.live:
        print("Live mode not required for V4; use blend. Aborting.")
        return 2
    payload = blend_from_prior()
    out = ROOT / "docs/research/complexity_routing_bench.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({
        "always_9b": payload["always_9b"],
        "routed": {k: payload["routed"][k] for k in (
            "avg_latency_s", "avg_correctness", "avg_persona", "n_fast", "n_main"
        )},
        "keep_9b_default": payload["keep_9b_default"],
    }, indent=2))
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
