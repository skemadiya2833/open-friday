"""Measure planner/tool-call parse failure rate with vs without JSON schema.

Uses a fixed prompt set against the installed main model. Writes
docs/research/parse_schema_bench.json.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PROMPTS = [
    'Return ONLY JSON: {"action":"WAIT","description":"pause"}',
    'Return ONLY JSON: {"tool":"web_search","args":{"query":"rust"}}',
    'Return ONLY JSON: {"action":"TYPE","text":"hello","x":100,"y":200}',
    'Return ONLY JSON with action COMPLETE and completion_evidence visible.',
    'Return ONLY JSON: {"action":"HOTKEY","keys":["ctrl","s"],"description":"save"}',
]


def _parse_ok(text: str) -> bool:
    try:
        data = json.loads(text.strip().strip("`").removeprefix("json").strip())
        return isinstance(data, dict) and ("action" in data or "tool" in data)
    except Exception:
        # try extract
        import re

        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            return False
        try:
            data = json.loads(m.group(0))
            return isinstance(data, dict) and ("action" in data or "tool" in data)
        except Exception:
            return False


def run(use_schema: bool) -> dict:
    from friday.models.local import query_model_text
    from friday.models.roles import PLANNER_SCHEMA, TOOL_CALL_SCHEMA

    rows = []
    for i, p in enumerate(PROMPTS):
        schema = TOOL_CALL_SCHEMA if "tool" in p else PLANNER_SCHEMA
        t0 = time.monotonic()
        out = query_model_text(
            p,
            format_json=not use_schema,
            format_schema=schema if use_schema else None,
            think=False,
            num_predict=120,
        )
        text = out.get("message") or out.get("raw") or json.dumps(out)
        if isinstance(out, dict) and out.get("action"):
            text = json.dumps(out)
            ok = True
        else:
            ok = _parse_ok(str(text))
        rows.append({"i": i, "ok": ok, "elapsed_s": round(time.monotonic() - t0, 2),
                     "preview": str(text)[:160]})
    n = len(rows)
    return {
        "use_schema": use_schema,
        "n": n,
        "parse_ok": sum(1 for r in rows if r["ok"]),
        "parse_fail_rate": round(1 - sum(1 for r in rows if r["ok"]) / max(1, n), 3),
        "rows": rows,
    }


def main() -> int:
    os.environ.setdefault("FRIDAY_AUTH", "off")
    before = run(False)
    after = run(True)
    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "before_schema": before,
        "after_schema": after,
    }
    out = ROOT / "docs" / "research" / "parse_schema_bench.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({"before": before["parse_fail_rate"], "after": after["parse_fail_rate"]}, indent=2))
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
