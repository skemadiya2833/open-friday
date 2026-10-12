"""Manual / browser test harness for the Tools & MCP page and approval dialog.

Starts the real Friday server (isolated audit log, port from FRIDAY_PORT) and registers a
harmless confirm-tier tool `harness_confirm_demo`. Once a browser page is polling, it requests
two approvals in sequence and writes the outcomes to the file given as argv[1]. Answer the
first with Allow and the second with Deny in the UI; expect outcomes "approved" then "denied".
No desktop control is involved. Use with scratch data only.
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
os.environ["PATH"] = str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"]
tmp = Path(tempfile.mkdtemp(prefix="friday_ui_harness_"))
os.environ.setdefault("FRIDAY_AUDIT_LOG", str(tmp / "audit.jsonl"))

import uvicorn  # noqa: E402

from friday.config import SERVER_PORT  # noqa: E402
from friday.safety.approval import get_approval_service  # noqa: E402
from friday.server.app import app  # noqa: E402
from friday.tools.registry import get_registry  # noqa: E402
from friday.tools.types import ToolRisk, ToolResult, ToolSpec, object_schema  # noqa: E402


def main() -> None:
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else tmp / "outcomes.json"
    reg = get_registry()
    reg.register(ToolSpec(
        name="harness_confirm_demo",
        description="Harmless demo tool used to exercise the approval dialog.",
        input_schema=object_schema({"note": {"type": "string"}}, []),
        handler=lambda args: ToolResult.text_result("demo executed"),
        risk=ToolRisk.CONFIRM,
        source="harness",
    ))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=SERVER_PORT, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    svc = get_approval_service()
    print(f"harness up on http://127.0.0.1:{SERVER_PORT}/  audit={os.environ['FRIDAY_AUDIT_LOG']}", flush=True)
    while not svc.has_responder():
        time.sleep(0.5)
    outcomes = []
    for i in (1, 2):
        r = reg.call("harness_confirm_demo", {"note": f"request {i}"}, caller="harness")
        outcomes.append({"n": i, "is_error": r.is_error, "text": r.text()[:120]})
        out_path.write_text(json.dumps(outcomes, indent=2), encoding="utf-8")
        print(outcomes[-1], flush=True)
    time.sleep(600)


if __name__ == "__main__":
    main()
