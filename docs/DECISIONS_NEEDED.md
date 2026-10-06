# Decisions made on the owner's behalf

Each entry: decision taken (safest reasonable default), reasoning, alternative.

## D-001: Brief file missing
`docs/CURSOR_BRIEF.md` is not in the repo. I worked from the brief text in the chat history (transcript) and the constraints it contained. Alternative: commit the brief verbatim to `docs/CURSOR_BRIEF.md` so future runs can re-read it. I did not fabricate a copy.

## D-002: mcp pinned to 2.3.0, not 2.0.0
2.3.0 is the version every test and live run used. 2.0.0 (stable) was never exercised. Alternative: pin 2.0.0 and re-run the MCP tests. See `docs/decisions/ADR-0006-mcp-sdk-version.md`.

## D-003: Approval granting requires same-origin browser headers
Granting needs `Origin` plus `Sec-Fetch-Site: same-origin`; polling can never grant (prompts time out as denied). A bare script or curl cannot approve. Limit: code running as the same OS user can forge those headers, and a computer-use agent could click the Allow button on screen. Alternative: out-of-band approval (hardware key, phone, or a native dialog on a secure desktop), more work and more friction. Recorded in the threat model.

## D-004: Vite dev origin is opt-in via FRIDAY_ALLOWED_ORIGINS
The Vite proxy rewrites `Host` but keeps `Origin`, so the strict check rejects it. Chosen: an exact-origin allow-list that is empty by default. Alternative: weaken the Host/Origin equality check (rejected, it removes the CSRF defence).

## D-005: Repository default model is already qwen3.5:9b
`.env` (and `/api/health`) report `qwen3.5:9b`, not qwen2.5vl:7b-q4_K_M. The baseline benchmark pins `qwen2.5vl:7b-q4_K_M` explicitly as requested. I did not touch `.env`.

## D-006: The owner's .env has SHELL_TOOLS_ENABLED=true
I did not change it. Policy keeps `run_shell` at `ask`, so each call needs an approval in the UI. Benchmarks and tests run with `SHELL_TOOLS_ENABLED=false`. Alternative: set it to false in `.env` (your file, so left alone).

## D-007: Benchmarks blank cloud API keys and set CLOUD_PROVIDER=none
So a benchmark can never send screenshots to Gemini/OpenAI even though .env has keys. Alternative: leave cloud fallback on (rejected: it would leak screen content and also contaminate local-model numbers).

## D-008: Hybrid agent derives element targets from the printed tree, not Windows-MCP labels
Windows-MCP's Click(label=N) indexes an internal list that Snapshot does not print, so label N cannot be matched to a visible element. The agent assigns its own ids to the printed elements and clicks the element's printed centre via loc. Alternative: guess that labels equal the order of printed interactive lines (UNVERIFIED, would silently click the wrong thing). Benchmark-only owner choices for the hybrid agent: the read-only Settings tasks lift the default "Settings" denial (anchored ^Settings$), and the local test-page titles are marked trusted so their Submit/Confirm buttons do not need a human. Both are passed by riday.bench.run, not defaults.

## D-009: Skill approval rules
Instruction-only agent proposals also need owner approval (the brief only demanded this for code-running skills). Imported skills with scripts can be approved but scripts are never executed by the loader; llowed-tools in SKILL.md never grants anything. Trust is bound to a content hash, so editing an approved skill revokes it. Alternative: auto-enable instruction-only proposals (rejected: instructions steer an agent that can click and type).
