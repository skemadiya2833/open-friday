"""G1 diagnosis: why does the hybrid agent see nothing in Chrome pages?

Launches a scratch Chrome profile on a local test page in several ways and records what Windows-MCP's Snapshot
returns (raw text dumped to docs/research/diag_chrome/), for different Snapshot options and over time.

    python scripts/diag_chrome_a11y.py
Uses only the benchmark's local test page and a throw-away profile. Keep hands off the mouse and keyboard.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
OUT = ROOT / "docs" / "research" / "diag_chrome"
VARIANTS = {
    "default": [],
    "force_renderer_accessibility": ["--force-renderer-accessibility"],
    "enable_features_uia": ["--enable-features=UiaProvider"],
}


def main() -> int:
    from friday.agent import uitree as U
    from friday.bench.site import Site
    from friday.mcp_client.manager import get_mcp_manager
    from friday.tools.registry import call_tool_result

    OUT.mkdir(parents=True, exist_ok=True)
    site = Site()
    m = get_mcp_manager()
    m.start("windows")
    for _ in range(90):
        if any(s.get("name") == "windows" and s.get("status") == "ready" for s in m.status()):
            break
        time.sleep(2)
    results = []
    try:
        for name, flags in VARIANTS.items():
            prof = tempfile.mkdtemp(prefix="friday_diag_chrome_")
            url = site.url("counter", "diag")
            proc = subprocess.Popen([CHROME, f"--user-data-dir={prof}", "--no-first-run", "--no-default-browser-check",
                                     "--disable-sync", "--new-window", *flags, url],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                for t in (2, 5, 9):
                    time.sleep(t if t == 2 else (3 if t == 5 else 4))
                    for opts in ({"use_dom": False}, {"use_dom": True}):
                        r = call_tool_result("windows__Snapshot", {"use_vision": False, "use_annotation": False, **opts},
                                             caller="diag", run_id=None)
                        text = r.text()
                        s = U.parse_snapshot(text)
                        inc = [e for e in s.elements if "increment" in e.name.lower()]
                        rec = {"variant": name, "t": t, "use_dom": opts["use_dom"], "focused": s.focused_title(),
                               "elements": len(s.elements), "increment_found": bool(inc), "chars": len(text)}
                        results.append(rec)
                        (OUT / f"{name}_t{t}_dom{int(opts['use_dom'])}.txt").write_text(text, encoding="utf-8")
                        print(rec, flush=True)
            finally:
                proc.kill()
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
                time.sleep(1.5)
    finally:
        m.stop("windows")
        site.close()
    (OUT / "summary.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
