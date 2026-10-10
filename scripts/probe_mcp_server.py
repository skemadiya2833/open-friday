"""Launch an MCP server over stdio and dump its real tool list + schemas.

Used to base tool-risk mappings on what a server actually exposes instead of its README.

Usage (from repo root, inside friday_env):
    python scripts/probe_mcp_server.py --out docs/research/windows_mcp_tools.json -- \
        uv tool run --python 3.14 --from windows-mcp==0.8.7 windows-mcp serve \
        --exclude-tools PowerShell,Registry
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import Client, StdioServerParameters


async def probe(command: str, args: list[str], env: dict[str, str], timeout: float) -> dict:
    params = StdioServerParameters(command=command, args=args, env=env)
    async with Client(params, read_timeout_seconds=timeout) as client:
        listed = await client.list_tools()
        tools = []
        for t in listed.tools:
            tools.append(
                {
                    "name": t.name,
                    "description": t.description,
                    "inputSchema": getattr(t, "input_schema", None) or getattr(t, "inputSchema", None),
                    "annotations": (
                        t.annotations.model_dump(exclude_none=True) if getattr(t, "annotations", None) else None
                    ),
                }
            )
        info = getattr(client, "server_info", None)
        return {
            "server_info": info.model_dump(exclude_none=True) if info is not None else None,
            "protocol_version": getattr(client, "protocol_version", None),
            "tool_count": len(tools),
            "tools": tools,
        }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--timeout", type=float, default=180.0)
    ap.add_argument("--env", action="append", default=[], help="KEY=VALUE (repeatable)")
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    ns = ap.parse_args()
    cmd = [c for c in ns.cmd if c != "--"]
    if not cmd:
        ap.error("missing server command after --")
    env = {k: v for k, v in (e.split("=", 1) for e in ns.env)}
    # Pass through what a subprocess needs to resolve uv/python on Windows.
    for key in ("PATH", "SystemRoot", "USERPROFILE", "LOCALAPPDATA", "APPDATA", "TEMP", "TMP"):
        if key in os.environ:
            env.setdefault(key, os.environ[key])
    result = asyncio.run(probe(cmd[0], cmd[1:], env, ns.timeout))
    out = Path(ns.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(f"{result['tool_count']} tools -> {out}")
    for t in result["tools"]:
        print(" -", t["name"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
