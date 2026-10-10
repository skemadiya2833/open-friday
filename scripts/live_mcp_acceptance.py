"""Stage A1: run the REAL Windows-MCP server through McpManager and the registry gate.

Safe by design: only DisplayInventory (read-only) and one toast Notification are called.
Writes docs/research/windows_mcp_live.json. Approvals are answered by this script playing
the human (in-process); the HTTP-level approval path is covered by tests/test_server_guard.py.
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

import yaml  # noqa: E402

from friday.mcp_client.config import parse_config  # noqa: E402
from friday.mcp_client.manager import McpManager  # noqa: E402
from friday.safety.approval import ApprovalService, set_approval_service  # noqa: E402
from friday.safety.audit import AuditLog, set_audit_log  # noqa: E402
from friday.safety.policy import Policy, set_policy  # noqa: E402
from friday.tools import registry as reg  # noqa: E402


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="friday_live_mcp_"))
    audit = AuditLog(str(tmp / "audit.jsonl"))
    svc = ApprovalService(default_timeout=30)
    set_audit_log(audit)
    set_policy(Policy())
    set_approval_service(svc)
    reg.reset_registry()

    raw = yaml.safe_load((ROOT / "config" / "mcp_servers.yaml").read_text(encoding="utf-8"))
    raw["servers"]["windows"]["enabled"] = True
    cfg = parse_config(raw)
    mgr = McpManager(cfg, registry=reg.get_registry())
    mgr.load()
    out: dict = {"checks": {}}
    t0 = time.time()
    mgr.start("windows")
    ready = mgr.wait_ready("windows", 240)
    out["startup_seconds"] = round(time.time() - t0, 1)
    st = mgr.status()[0]
    out["status"] = {k: st[k] for k in ("status", "error", "command", "server_info")}
    out["checks"]["server_ready"] = ready
    if not ready:
        print(json.dumps(out, indent=2, default=str))
        mgr.shutdown()
        return 1

    names = sorted(t["name"] for t in st["tools"])
    out["tool_names"] = names
    out["tools"] = [
        {"name": t["name"], "registry_name": t["registry_name"], "tier": t["risk"], "annotations": t["annotations"]}
        for t in st["tools"]
    ]
    out["schemas"] = {
        s.name: s.input_schema for s in reg.get_registry().list() if s.name.startswith("windows__")
    }
    out["checks"]["powershell_registry_excluded"] = not ({"PowerShell", "Registry"} & set(names))
    out["checks"]["telemetry_env_off"] = (
        cfg.servers["windows"].env.get("ANONYMIZED_TELEMETRY") == "false"
    )
    out["checks"]["pinned_launch"] = "windows-mcp==0.8.7" in st["command"]
    out["tier_by_tool"] = {t["name"]: t["risk"] for t in st["tools"]}

    # Safe-tier call: no approval expected.
    r = reg.get_registry().call("windows__DisplayInventory", {}, caller="acceptance")
    out["safe_call"] = {"is_error": r.is_error, "text": r.text()[:400]}
    out["checks"]["safe_call_ok"] = not r.is_error

    # Confirm-tier call through a real approval (human stand-in answers it).
    svc.touch()
    seen: dict = {}

    def human(approve: bool):
        for _ in range(100):
            svc.touch()
            p = svc.list_pending()
            if p:
                seen.setdefault("pending", []).append({k: p[0].get(k) for k in ("tool", "risk", "caller")})
                svc.resolve(p[0]["id"], approve, who="acceptance-script")
                return
            time.sleep(0.1)

    th = threading.Thread(target=human, args=(True,))
    th.start()
    r = reg.get_registry().call(
        "windows__Notification",
        {"app_id": "Friday", "title": "Friday acceptance test", "message": "Scratch notification, safe to ignore."},
        caller="acceptance",
    )
    th.join()
    out["confirm_call_approved"] = {"is_error": r.is_error, "text": r.text()[:300], "pending_seen": seen}
    out["checks"]["confirm_call_approved_ok"] = (not r.is_error) and bool(seen.get("pending"))

    th = threading.Thread(target=human, args=(False,))
    th.start()
    r = reg.get_registry().call(
        "windows__Notification", {"app_id": "Friday", "title": "should not appear", "message": "denied"}, caller="acceptance"
    )
    th.join()
    out["confirm_call_denied"] = {"is_error": r.is_error, "text": r.text()[:200]}
    out["checks"]["confirm_call_denied_blocked"] = r.is_error and "denied" in r.text().lower()

    recs = audit.tail(20)
    out["audit"] = [
        {k: x.get(k) for k in ("tool", "risk", "caller", "outcome", "approver")}
        for x in recs
        if str(x.get("tool", "")).startswith("windows__")
    ]
    ok, msg = audit.verify()
    out["checks"]["audit_chain_ok"] = ok
    out["checks"]["audit_has_approved_and_denied"] = any(
        a["outcome"] and "den" in str(a["outcome"]) for a in out["audit"]
    ) and any("acceptance-script" in str(a["approver"]) for a in out["audit"])

    mgr.shutdown()
    dest = ROOT / "docs" / "research" / "windows_mcp_live.json"
    dest.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"checks": out["checks"], "startup_seconds": out["startup_seconds"]}, indent=2))
    return 0 if all(out["checks"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
