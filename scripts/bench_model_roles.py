"""Stage P: measure installed models for role assignment. No downloads.

Writes docs/research/model_roles_bench.json
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from friday.models.roles import PLANNER_SCHEMA, TOOL_CALL_SCHEMA  # noqa: E402


def vram_mb() -> int | None:
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            text=True,
            timeout=5,
        )
        return int(out.strip().splitlines()[0])
    except Exception:
        return None


def unload(model: str) -> None:
    import httpx
    from friday.config import OLLAMA_HOST

    try:
        httpx.post(f"{OLLAMA_HOST}/api/generate", json={"model": model, "prompt": "", "keep_alive": 0}, timeout=60)
    except Exception:
        pass


def chat(model: str, prompt: str, *, schema=None, num_predict=128, num_ctx=2048) -> dict:
    from friday.models.local import query_model_text

    t0 = time.perf_counter()
    r = query_model_text(
        prompt,
        format_json=schema is None,
        format_schema=schema,
        num_predict=num_predict,
        num_ctx=num_ctx,
        model=model,
    )
    dt = time.perf_counter() - t0
    msg = (r.get("message") or r.get("raw") or "").strip()
    parsed = None
    try:
        parsed = json.loads(msg)
    except Exception:
        pass
    return {"s": round(dt, 3), "chars": len(msg), "json_ok": parsed is not None, "sample": msg[:240]}


def main() -> int:
    models = [
        "qwen3.5:4b",
        "qwen3.5:9b",
        "qwen3-vl:8b-instruct",
        "qwen2.5vl:7b-q4_K_M",
    ]
    # coder measured alone, short — expect RAM spill
    tool_prompt = (
        'System: You are a tool router. Static tools: web_search, memory_search, schedule_task.\n'
        'User: remind me in 5 minutes to stretch\n'
        'Respond with JSON only matching the schema.'
    )
    plan_prompt = (
        'System: Desktop planner. Static actions: WAIT, TYPE, HOTKEY, COMPLETE.\n'
        'User objective: Open Notepad.\n'
        'Screen: (empty desktop)\n'
        'Respond with one JSON action.'
    )
    greet_prompt = "Say a 8-word greeting to the boss. Plain text only."

    report: dict = {
        "ollama_version": None,
        "mtp_note": "MTP speculative decoding docs target Ollama >=0.32 / MLX; this host is older — not enabled.",
        "flash_attn_kv": None,
        "rows": [],
        "co_residency": [],
        "windows_mcp_preview": None,
    }
    try:
        import httpx
        report["ollama_version"] = httpx.get("http://127.0.0.1:11434/api/version", timeout=5).json().get("version")
    except Exception as exc:
        report["ollama_version"] = f"error:{exc}"

    # Flash attention + q8 KV — env for this process only; measure one 9b call if set.
    fa = os.environ.get("OLLAMA_FLASH_ATTENTION")
    kv = os.environ.get("OLLAMA_KV_CACHE_TYPE")
    report["flash_attn_kv"] = {
        "OLLAMA_FLASH_ATTENTION": fa,
        "OLLAMA_KV_CACHE_TYPE": kv,
        "note": "Must be set on the Ollama service, not only this script. Untouched here (no persistent system change).",
    }

    for m in models:
        print(f"=== {m}", flush=True)
        unload(m)
        time.sleep(0.5)
        v0 = vram_mb()
        t_load = time.perf_counter()
        row = {"model": m, "vram_idle_mb": v0}
        try:
            g = chat(m, greet_prompt, schema=None, num_predict=64)
            row["greet"] = g
            row["load_and_greet_s"] = g["s"]
            row["vram_after_mb"] = vram_mb()
            t = chat(m, tool_prompt, schema=TOOL_CALL_SCHEMA, num_predict=128)
            row["tool_schema"] = t
            p = chat(m, plan_prompt, schema=PLANNER_SCHEMA, num_predict=128)
            row["plan_schema"] = p
        except Exception as exc:
            row["error"] = f"{type(exc).__name__}: {exc}"
        row["wall_s"] = round(time.perf_counter() - t_load, 3)
        report["rows"].append(row)
        unload(m)
        time.sleep(0.3)

    # Co-residency: warm 4b then 9b without unload between
    print("=== co-residency 4b+9b", flush=True)
    unload("qwen3.5:4b")
    unload("qwen3.5:9b")
    time.sleep(0.5)
    v0 = vram_mb()
    try:
        chat("qwen3.5:4b", greet_prompt, num_predict=32)
        v1 = vram_mb()
        chat("qwen3.5:9b", greet_prompt, num_predict=32)
        v2 = vram_mb()
        report["co_residency"].append({
            "pair": "4b+9b",
            "vram_start": v0,
            "vram_after_4b": v1,
            "vram_after_9b": v2,
            "note": "Ollama may evict; values are observational.",
        })
    except Exception as exc:
        report["co_residency"].append({"pair": "4b+9b", "error": str(exc)})

    print("=== co-residency 9b+3-vl", flush=True)
    unload("qwen3.5:9b")
    unload("qwen3-vl:8b-instruct")
    time.sleep(0.5)
    v0 = vram_mb()
    try:
        chat("qwen3.5:9b", greet_prompt, num_predict=32)
        v1 = vram_mb()
        chat("qwen3-vl:8b-instruct", greet_prompt, num_predict=32)
        v2 = vram_mb()
        report["co_residency"].append({
            "pair": "9b+3-vl",
            "vram_start": v0,
            "vram_after_9b": v1,
            "vram_after_vl": v2,
        })
    except Exception as exc:
        report["co_residency"].append({"pair": "9b+3-vl", "error": str(exc)})

    # coder: one short call only
    print("=== coder 30b (expect spill)", flush=True)
    unload("qwen3-coder:30b")
    v0 = vram_mb()
    t0 = time.perf_counter()
    try:
        c = chat("qwen3-coder:30b", "Return JSON {\"ok\":true}", schema=None, num_predict=32, num_ctx=1024)
        report["coder"] = {"vram_before": v0, "vram_after": vram_mb(), "result": c, "s": round(time.perf_counter() - t0, 3)}
    except Exception as exc:
        report["coder"] = {"vram_before": v0, "error": str(exc), "s": round(time.perf_counter() - t0, 3)}
    unload("qwen3-coder:30b")

    # Windows 11 native MCP / Agent Workspace — research only
    build = None
    try:
        build = subprocess.check_output(
            ["reg", "query", r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion", "/v", "CurrentBuild"],
            text=True, timeout=5,
        )
    except Exception as exc:
        build = str(exc)
    report["windows_mcp_preview"] = {
        "build_query": build,
        "note": (
            "Windows 11 on-device MCP registry / Agent Workspace are preview features. "
            "This run does not enable them. If Agent Workspace isolates input, it could reduce "
            "hands-off-keyboard risk during benches — UNVERIFIED on this PC."
        ),
    }

    report["recommendation"] = (
        "Keep default qwen3.5:9b unified. Optional FRIDAY_MODEL_ROLES=true can route greetings to 4b "
        "after reviewing rows. Do not co-reside 30b coder. MTP not available on Ollama 0.30.10."
    )

    out = ROOT / "docs" / "research" / "model_roles_bench.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("Wrote", out, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
