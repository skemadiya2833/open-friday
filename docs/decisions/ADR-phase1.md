# Phase 1 decisions (tool layer v2 and MCP client)

Format: context, decision, consequences. Evidence for each is in `docs/ARCHITECTURE_AUDIT.md`.

## ADR-0001: One registry, one gate, one audit trail
Context: tools were reachable from three code paths (ReAct loop, agent executor, skills) with different safety checks. The `read_file`/`write_file` path check was a string-prefix test that a junction escaped (reproduced in Phase 0).
Decision: every call goes through `ToolRegistry.call`: JSON Schema validation, policy (allow/ask/deny), approval, handler, hash-chained audit. Path access uses `resolve_within`.
Consequences: legacy `call_tool` keeps its string return. Behaviour changes: `run_shell` is denied by default; `write_file` is allowed by `config/policy.yaml` (it is workspace-confined).

## ADR-0002: MCP client built on the official `mcp` SDK v2
Context: Windows-MCP and most ecosystem servers speak MCP over stdio.
Decision: `McpManager` owns a private asyncio loop thread; each server runs in a single task holding an `AsyncExitStack`. Tools are registered as `<server>__<tool>`. Server-declared annotations are ignored for risk unless `trust_annotations: true`; tiers come from our config. MCP output is marked untrusted.
Consequences: a misbehaving server cannot raise its own tier. Servers are disabled by default and have a kill switch.

## ADR-0003: Windows-MCP runs as an isolated `uv` process
Context: Windows-MCP 0.8.7 requires Python >= 3.14 and ships its own dependencies; installing it into the Friday venv couples unrelated dependency trees.
Decision: launch with `uv tool run --python 3.14 --from windows-mcp==0.8.7`, with `PowerShell` and `Registry` tools excluded, telemetry env forced off, and an environment whitelist (no inherited secrets).
Consequences: first start downloads packages (startup timeout 180 s). Not yet exercised end to end inside the manager; only probed directly.

## ADR-0004: Single hardened shell runner, denied by default
Decision: PowerShell via argv (no `shell=True`), cwd confined to the workspace, policy-bounded timeout with process-tree kill, redacted and truncated output. Tier `dangerous` maps to `deny`; enabling requires editing the policy file and setting `SHELL_TOOLS_ENABLED`.

## ADR-0005: Replace CORS `*` with a request guard (deviation: pulled forward from Phase 6)
Context: approvals and the MCP kill switch are HTTP endpoints. With `allow_origins=["*"]` any visited web page could approve its own request. Hardening could not wait for Phase 6.
Decision: no CORS headers; reject unknown Host (DNS rebinding) and foreign Origin (CSRF, WebSocket); require `FRIDAY_API_TOKEN` and refuse to start on a non-loopback bind without it.
Consequences: any external front-end on another origin stops working. Local processes running as the same user are out of scope (they can already do everything Friday can).
