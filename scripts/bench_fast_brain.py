"""Compare qwen3.5:4b (fast) vs qwen3.5:9b (main) on the 20-prompt persona set.

Does not change defaults. Writes docs/research/fast_brain_bench.json.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.eval_persona import PROMPTS, score_reply  # noqa: E402


def run_model(model: str, limit: int = 20) -> dict:
    from friday.models.local import query_model_text
    from friday.persona import system_prompt

    rows = []
    for p in PROMPTS[:limit]:
        t0 = time.monotonic()
        out = query_model_text(
            "",
            messages=[
                {"role": "system", "content": system_prompt("chat")},
                {"role": "user", "content": p["text"]},
            ],
            think=False,
            num_predict=160,
            model=model,
        )
        reply = (out.get("message") or out.get("raw") or "").strip()
        if out.get("routing") == "FALLBACK_TO_CLOUD":
            reply = f"[UNVERIFIED: {out.get('reason')}]"
        sc = score_reply(p, reply, "off")
        rows.append({
            "id": p["id"],
            "cat": p["cat"],
            "elapsed_s": round(time.monotonic() - t0, 2),
            "reply": reply[:400],
            **sc,
        })
    n = max(1, len(rows))
    return {
        "model": model,
        "n": len(rows),
        "avg_latency_s": round(sum(r["elapsed_s"] for r in rows) / n, 3),
        "avg_correctness": round(sum(r["correctness"] for r in rows) / n, 3),
        "avg_concision": round(sum(r["concision"] for r in rows) / n, 3),
        "avg_persona": round(sum(r["persona"] for r in rows) / n, 3),
        "rows": rows,
    }


def main() -> int:
    os.environ.setdefault("FRIDAY_AUTH", "off")
    os.environ["FRIDAY_HUMOR"] = "off"
    four = run_model("qwen3.5:4b", 20)
    nine = run_model("qwen3.5:9b", 20)
    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "fast_4b": four,
        "main_9b": nine,
        "recommend_default_change": (
            four["avg_correctness"] >= nine["avg_correctness"]
            and four["avg_latency_s"] < nine["avg_latency_s"] * 0.7
            and four["avg_persona"] >= 0.95
        ),
    }
    out = ROOT / "docs" / "research" / "fast_brain_bench.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({
        "4b": {k: four[k] for k in ("avg_latency_s", "avg_correctness", "avg_persona")},
        "9b": {k: nine[k] for k in ("avg_latency_s", "avg_correctness", "avg_persona")},
        "change_default": payload["recommend_default_change"],
    }, indent=2))
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
