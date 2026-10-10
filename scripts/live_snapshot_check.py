"""Live check of the Snapshot parser against the real Windows-MCP (read-only: only calls Snapshot).

    python scripts/live_snapshot_check.py
Writes docs/research/live_snapshot_sample.txt (the raw text) and prints what the parser found.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from friday.agent import uitree as U  # noqa: E402
from friday.mcp_client.manager import get_mcp_manager  # noqa: E402
from friday.tools.registry import call_tool_result  # noqa: E402


def main() -> int:
    m = get_mcp_manager()
    m.start("windows")
    for _ in range(90):
        if any(s.get("name") == "windows" and s.get("status") == "ready" for s in m.status()):
            break
        time.sleep(2)
    try:
        r = call_tool_result("windows__Snapshot", {"use_vision": False, "use_annotation": False, "use_dom": False},
                             caller="live-check", run_id=None)
        print("is_error:", r.is_error, "blocks:", [(b.get("type"), len(str(b.get("text", "")))) for b in r.content],
              "structured:", type(r.structured).__name__)
        text = r.text()
        (ROOT / "docs" / "research" / "live_snapshot_sample.txt").write_text(text, encoding="utf-8")
        s = U.parse_snapshot(text)
        print(f"chars={len(text)} focused={s.focused_title()!r} windows={len(s.windows)} elements={len(s.elements)} "
              f"displays={s.displays} truncated={s.truncated}")
        for e in s.elements[:6]:
            print("  ", e.line(), (e.x, e.y))
        return 0 if s.elements else 1
    finally:
        m.stop("windows")


if __name__ == "__main__":
    raise SystemExit(main())
