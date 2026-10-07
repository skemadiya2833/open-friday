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

- B2 Benchmark harness: PASS (self-test 29/29: negative controls fail, oracle passes, cleanup leaves pre-existing windows alone; Calculator UIA read verified; local pages' JS verified in a browser). 26 tasks x 3 reps. UNVERIFIED: Notepad window cleanup/kill path.
- B1 live: hotkey halted the REAL vision loop in 1.41 s (docs/research/live_estop_check.json): PASS.
- B3 baseline run started 2026-10-06T11:41:45, pid 17504; output docs/research/bench_baseline_legacy_qwen25vl.json (resumable with --resume).

### Stage C (in progress)
- C1 hybrid agent: code + tests DONE, live run UNVERIFIED until baseline finishes. Files: friday/agent/{uitree,guard,hybrid}.py, friday/safety/grant.py (run grants; registry.call(force_ask=...)), AGENT_BACKEND=hybrid switch in runs.py (default stays legacy). 36 tests (parser, guard, loop, prompt injection with an obedient scripted model, grants). Windows-MCP never prints element labels, so the agent maps its own ids to printed centre coordinates (D-008).
- C2 prompt-injection tests: PASS in tests/test_hybrid.py (window title, page text, denylisted apps, launch of denied app, fenced untrusted text). Live injection test against the real model: NOT YET RUN.
- C3 hybrid benchmark + model comparison: NOT YET RUN (waiting for baseline).

### Stage D (in progress)
- D1 agentskills.io loader: code + 23 tests DONE (friday/skills/agentskills.py, routes_skillmd.py, builtin tools skills_list/skill_activate/skill_read/skill_propose, proposal loop behind SKILL_PROPOSALS=true). Spec fetched from agentskills.io/specification on 2026-10-06.

### Stage D2/D3 (docs done; measurements pending until baseline ends)
- D2 voice code + 10 plumbing tests DONE (`friday/voice/*`, `scripts/voice_*`). Measurements (TTS Kokoro/Piper/SAPI, STT+vision VRAM, end-to-end latency) deferred: they would perturb the running baseline. 
- D3 `docs/VOICE_SAMPLES.md` written. `large-v3-turbo` float16 stays PROVISIONAL / UNVERIFIED on the owner's voice.

### Stage E
- E1 DONE: `docs/research/PHASE5_OPTIONS.md` (ranked, with sources). Python 3.14 binary-wheel resolve check passed for bleak 3.0.2, pycaw 20260927, psutil 7.2.2, playwright 1.63.0 (does not prove the features work here). Built only `friday/experimental/sensors.py` (read-only, stdlib+ctypes, off unless FRIDAY_SENSORS=true, 4 tests; live read verified: CPU, RAM, disks, GPU).
- E2 mostly DONE: startup config validation (`friday/diagnostics.py`, 14 tests), JSON logs with run ids (`friday/logs.py`), `/health` page + `/api/health/detail`, atomic state writes (`friday/atomic.py`: plan, sessions, skills registry), google-generativeai -> google-genai (API verified in an isolated venv with google-genai 2.28.0; code tested with a fake client; a LIVE Gemini call is UNVERIFIED and the default model `gemini-2.5-flash` is a guess, override with GEMINI_MODEL), core.lock.txt recompiled (friday_env NOT yet updated to it), CI workflow `.github/workflows/ci.yml` (written, NEVER RUN: UNVERIFIED), THREAT_MODEL.md with web-server review (fixed unbounded voice upload), README and CONTRIBUTING updated, ruff F/E9 clean. 174 tests pass (hotkey tests excluded while benchmark runs).
- E2 remaining: live server start check of the new lifespan validation (after baseline).

### Final
- C3 hybrid 6/26 vs baseline 5/78; model subset tie (4/6 each); no default changed. D2 measurements skipped by owner request. FINAL_REPORT.md written. Tags stage-C/D/E.

## Stage G (diagnose) - DONE
- G1 PASS (root causes verified; generic browser-tree settle; fingerprint+page_text). Live counter run: sees page, clicks work, does not stop at N (model limit).
- G2 PASS (multi-line names kept; 3 tests). Repeat guard now 6 (launch 2) because legit repeated clicks were blocked.


## Stage H/I/J - STOPPED BY OWNER (no more live tests)
- H1 PARTIAL: hybrid 78/78 runs done (21 passed); legacy rerun stopped at 47/78 on owner request. Raw: docs/research/bench_H_*.json. Compare with scripts/bench_compare.py. UNVERIFIED: full legacy baseline, H3 VRAM, Stage I benchmarks, J.
- Owner-reported stalls fixed WITHOUT live testing (unit tests only): safe-dismiss buttons (Don't send/No/Cancel/Close) are allowed; 'done' before any action is rejected; denied/unanswered approvals tell the model not to retry and to pick a safe choice; prompt rule for crash/error pop-ups. UNVERIFIED live (OBS crash dialog).


## Stage K (stall detection, safe recovery) - DONE
- K1 PASS (unit + partial live): friday/agent/stall.py (no-progress detector, call timeouts for every tool/model call, hung-window detector via title/status + Win32 IsHungAppWindow, recovery ladder reobserve > Escape > alternative > vision > structured fail). Integrated in hybrid loop; failures carry `agent_failure` {kind, detail, recovery_tried, elapsed_s, steps}.
- K2 PASS (unit): ApprovalService attended/unattended; unattended denies at once ("denied:unattended"); attended beeps (voice hook pluggable, UNVERIFIED) and waits. Benchmarks run unattended by default (`--attended` to opt out).
- K3 PASS (unit incl. adversarial): friday/agent/dialogs.py. Windows-MCP does NOT expose dialog body labels (verified live), so the title + button set are evidence too.
- K4 PARTIAL live: WinForms synthetic dialogs (friday/bench/synth_dialog.ps1, scripts/synth_live.py; Tk is invisible to UI Automation). crash: PASS live ("Don't send" chosen, 5.8 s). save: PASS live (nothing discarded; no button pressed). hung: UNVERIFIED live - the simulator was never reported as hung (Windows only flags hang on pending input); covered by unit tests.
- Live time used so far: ~12 min of the 90 min budget.

## 2026-10-07 voice / memory / reminders
- Voice: fillers are captions only (no spoken "give me a minute" then a greeting); history is restated in the prompt; Clear chat is in the header and next to Transmit; orb nudges with speech; Realtime pause 280ms.
- Memory Core lists learned facts, notes, desktop, experience, plan, reminders, and actual chat turns.
- Scheduling is agentic: no approval JSON for reminders; follow-ups after "when?" stay on the tasks skill; due jobs toast and Friday pops the reminder in chat.

- Loop breaker: state-cycle detection (3rd visit), forced strategy change, stop after 3 cycles; self-undo guard (no re-click into typed field, no clear+retype). Unit tested.
- Composite action: multi-line 	ype is one action (click once, Enter between lines). Unit tested.
- Tools-first router (friday/agent/router.py): writes new text files for 'type ... save as PATH' objectives, verified by read-back; off in benchmarks (--tools-first). Unit tested. UNVERIFIED on real runs.
- Voice: Realtime/Relaxed pacing + speech speed settings, live overlay (orb, captions, fillers), sentence-streamed TTS. Checked in browser only; mic/TTS audio UNVERIFIED.
- Research: docs/research/agent_failure_modes.md.

