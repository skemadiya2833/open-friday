"""Second-client / forged-header probe against a running Friday server.

Usage:
  # Terminal A: FRIDAY_AUTH=local python main.py --server
  # Terminal B:
  python scripts/lan_auth_probe.py [--base http://127.0.0.1:8787]

Writes docs/research/lan_auth_probe.json with raw results.
Does NOT need a phone — uses forged Host/Origin from this machine (second "device" view).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _req(url: str, *, method: str = "GET", headers: dict | None = None, body: bytes | None = None,
         timeout: float = 5.0) -> dict:
    h = dict(headers or {})
    req = urllib.request.Request(url, data=body, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
            raw = r.read()
            return {"ok": True, "status": r.status, "body": raw[:500].decode("utf-8", "replace"),
                    "headers": dict(r.headers)}
    except urllib.error.HTTPError as e:
        raw = e.read() if e.fp else b""
        return {"ok": False, "status": e.code, "body": raw[:500].decode("utf-8", "replace"),
                "reason": str(e.reason)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "status": None, "error": f"{type(exc).__name__}: {exc}"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8787")
    ap.add_argument("--out", default=str(ROOT / "docs" / "research" / "lan_auth_probe.json"))
    args = ap.parse_args()
    base = args.base.rstrip("/")
    host = base.split("://", 1)[-1]
    results = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "base": base, "cases": []}

    cases = [
        ("unauth_GET_tools", "GET", f"{base}/api/tools",
         {"Host": host, "Origin": base}, None),
        ("unauth_POST_chat", "POST", f"{base}/api/chat",
         {"Host": host, "Origin": base, "Content-Type": "application/json"},
         b'{"message":"hi"}'),
        ("unauth_POST_approval_grant", "POST", f"{base}/api/approvals/x/approve",
         {"Host": host, "Origin": base, "Content-Type": "application/json"},
         b"{}"),
        ("forged_Origin_pair", "POST", f"{base}/api/auth/pair/request",
         {"Host": host, "Origin": "http://evil.example", "Content-Type": "application/json"},
         b'{"device_name":"evil"}'),
        ("forged_Host_tools", "GET", f"{base}/api/tools",
         {"Host": "evil.example", "Origin": "http://evil.example"}, None),
        ("forged_Host_loopback_mismatch", "GET", f"{base}/api/health",
         {"Host": "192.168.1.1"}, None),
        ("unauth_SSE_chat_stream", "POST", f"{base}/api/chat/stream",
         {"Host": host, "Origin": base, "Content-Type": "application/json", "Accept": "text/event-stream"},
         b'{"message":"hi"}'),
        ("unauth_runs_sse", "GET", f"{base}/api/runs/fake/events",
         {"Host": host, "Origin": base}, None),
    ]

    for name, method, url, headers, body in cases:
        row = {"name": name, "method": method, "url": url, "request_headers": headers}
        row["response"] = _req(url, method=method, headers=headers, body=body)
        results["cases"].append(row)
        print(f"{name}: {row['response'].get('status')} {row['response'].get('body','')[:80]}")

    # WebSocket without cookie
    ws_row = {"name": "unauth_websocket", "url": base.replace("http", "ws") + "/ws"}
    try:
        import asyncio

        import websockets

        async def _ws():
            uri = ws_row["url"]
            try:
                async with websockets.connect(
                    uri,
                    additional_headers={"Origin": "http://evil.example", "Host": host},
                    open_timeout=3,
                ) as ws:
                    await ws.ping()
                    return {"ok": True, "status": "connected_unexpected"}
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

        ws_row["response"] = asyncio.run(_ws())
    except ImportError:
        # stdlib fallback via httpx/starlette not available — use raw socket close expectation
        try:
            import websocket  # type: ignore

            websocket.create_connection(
                ws_row["url"],
                header=[f"Origin: http://evil.example", f"Host: {host}"],
                timeout=3,
            )
            ws_row["response"] = {"ok": True, "status": "connected_unexpected"}
        except Exception as exc:  # noqa: BLE001
            ws_row["response"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    results["cases"].append(ws_row)
    print(f"unauth_websocket: {ws_row['response']}")

    # Expectation summary
    expect_deny = {"unauth_GET_tools", "unauth_POST_chat", "unauth_POST_approval_grant",
                   "forged_Origin_pair", "forged_Host_tools", "forged_Host_loopback_mismatch",
                   "unauth_SSE_chat_stream", "unauth_runs_sse", "unauth_websocket"}
    passed = 0
    failed = 0
    for c in results["cases"]:
        name = c["name"]
        resp = c.get("response") or {}
        status = resp.get("status")
        if name == "unauth_websocket":
            ok = (not resp.get("ok")) or status == "connected_unexpected" and False
            # pass if connection failed / closed
            ok = not resp.get("ok", False) or resp.get("status") != "connected_unexpected"
        elif name == "forged_Host_loopback_mismatch":
            # /api/health is public but Host must still be allow-listed
            ok = status in (403, None) or not resp.get("ok", True)
        else:
            ok = status in (401, 403)
        c["pass"] = bool(ok)
        passed += int(ok)
        failed += int(not ok)

    results["summary"] = {"passed": passed, "failed": failed, "expect_deny": sorted(expect_deny)}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results["summary"], indent=2))
    print(f"Wrote {args.out}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
