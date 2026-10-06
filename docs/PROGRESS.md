# Progress (resume from here if context resets)

Branch: `upgrade/research-first`. Never merge, never push. Tags: stage-A .. stage-E.
Statuses: PASS, FAIL, BLOCKED, SKIPPED, UNVERIFIED (with evidence).

## Done before this run
- Phase 0 audit (`docs/ARCHITECTURE_AUDIT.md`), Phase 1 core (commit c28236c): tool layer v2, MCP manager, request guard, Tools page. 73 tests pass, 1 skipped.

## Note on the brief
`docs/CURSOR_BRIEF.md` does not exist in the repository (the brief was only given in chat). See DECISIONS_NEEDED D-001.

## Task log
(append below: task, status, evidence, next, blockers)

### Stage A
- A1 Live Windows-MCP through manager: PASS. `scripts/live_mcp_acceptance.py`, output `docs/research/windows_mcp_live.json`. Server ready in ~2-3 s (warm uv cache), 18 tools, PowerShell and Registry absent, pinned launch `windows-mcp==0.8.7` under uv, DisplayInventory (safe) ok with `policy:allow`, Notification (confirm) approved then denied through real ApprovalService, audit chain verified. UNVERIFIED: that no telemetry traffic leaves the process (only the env setting and upstream README were checked; no network capture).
- A2 Browser test of Tools page: PASS in the Cursor browser. Real clicks: Allow once and Deny (outcomes approved/denied, audit shows both), Start, Stop; Start again and kill switch via DOM click. Found and fixed: collapsed card layout (flex shrink), stale tool count after stop, no auto-refresh.
- A3 Fresh venv (Python 3.14.6, pip, `requirements/core.lock.txt` + dev lock): PASS. 76 tests pass; server starts on a custom port, health 200, evil Origin 403. Install took 108 s. Voice lock not installed in that test (UNVERIFIED). Added requirements split and locks, README install section.
- A4 Skipped test: it was `test_symlink_pointing_outside_is_blocked` (symlinks need Developer Mode). Security test, so it now simulates the link when real symlink creation is refused. 76 passed, 0 skipped.
- A5 Approval presence: PASS. Polling only marks presence; granting needs same-origin browser headers; tests prove polling-only cannot approve and bare scripts get 403 on grant.
- A6 Vite shell: PASS. Found that proxied POST was 403 (Host rewritten, Origin kept). Added FRIDAY_ALLOWED_ORIGINS (exact, default empty). Verified through the real Vite dev server in a browser (POST 200, WS open, evil origin 403, direct cross-origin fetch blocked). React shell has no approval UI.
- A7 ADR for MCP SDK: PASS (`ADR-0006`). Pin mcp==2.3.0; lock has anyio 4.15.1, pydantic 2.13.5.
- Also: stripped a stray BOM from two files.

### Stage B
- B1 Emergency stop + per-run events + run manager: PASS (tests). Files: `friday/safety/estop.py` (RegisterHotKey, default Ctrl+Alt+F12, env FRIDAY_STOP_HOTKEY, FRIDAY_ESTOP=false disables), `friday/agent/runs.py`, `friday/agent/control.py` (ContextVar controller, live-controller registry, cancel_all_agents), `friday/ui/events.py` (run_id on every event), `friday/server/routes_runs.py` (/api/runs, per-run SSE, /api/runs/{id}/cancel, /api/estop), computer_use handler now uses RunManager (exclusive, per-run forwarding). 90 tests pass, including injecting the real Ctrl+Alt+F12 chord with keybd_event and observing a fake agent halt, and a hotkey-conflict test. UNVERIFIED so far: halting the REAL vision loop (run_agent + Ollama) with the hotkey; done as a pre-flight in B3.
