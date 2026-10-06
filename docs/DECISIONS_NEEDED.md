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

## D-010: STT default in code changed to `large-v3-turbo`; your `.env` still says `base`
The code default (`VOICE_STT_MODEL`) is now `large-v3-turbo` (fits easily next to the vision model, see `docs/research/stt_bench.json`). Your `.env` overrides it with `base`, so nothing changes for you until you edit `.env`. Accuracy on your voice is UNVERIFIED until you run `docs/VOICE_SAMPLES.md`. Alternative: keep `base` (fastest, least accurate).

## D-011: Wake word is the pretrained `hey_jarvis`; barge-in default is "wake"
openWakeWord has no pretrained "hey friday"; a custom model needs training and is UNVERIFIED. Barge-in defaults to requiring the wake word (no echo cancellation, so listening for speech while Friday speaks through speakers would make it interrupt itself). `vad` mode is for headphones. Alternative: train a custom wake word.

## D-012: Benchmark timeout is 120 s per run (legacy and hybrid alike)
The legacy loop needs about 12 s per step with this model, so 100 s cut runs to about 8 steps. Both the baseline and the hybrid run use 120 s and 15 steps, so the comparison is like for like. An earlier 100 s partial attempt was contaminated (a package install corrupted the environment mid-run) and is kept only as evidence (`bench_baseline_attempt1_PARTIAL_legacy_timeout100.json`).

## D-013: Hybrid prompt was tuned after seeing live failures on three smoke tasks
Smoke tasks: notepad_open, calc_add, notepad_type_save (one run each, before the real benchmark). Fixes were generic (launch apps instead of failing, `id` must be a number, type into the focused window when there is no text field, feedback after a successful launch), but the model saw hints such as "digits work as keys in Calculator". This is mild tuning toward the benchmark apps; the legacy baseline had no such tuning. Alternative: freeze the prompt before any live run (rejected: the first live run showed the parser did not even match the real Windows-MCP output format).

## D-014: Config now refuses to start on invalid values
Bad port, bad booleans, unknown `CLOUD_PROVIDER`/`AGENT_BACKEND`, or a non-loopback `FRIDAY_HOST` without `FRIDAY_API_TOKEN` stop startup with a readable message. Missing cloud keys are only warnings. Alternative: warn only (rejected for the token case: silently exposing the desktop agent is worse than failing to start).

## D-015: google-genai migration uses model `gemini-2.5-flash`, overridable with `GEMINI_MODEL`
The old code asked for `gemini-1.5-pro-latest`, which no longer exists. I cannot verify a live call without your key, so the name is a best guess and the call path is UNVERIFIED (API signatures were verified against google-genai 2.28.0). Alternative: pick `gemini-2.5-pro` (slower, dearer). `friday_env` still has the OLD package installed until you run `uv pip install -r requirements/core.lock.txt`; the code now imports `google.genai`, so the cloud fallback will fail (and return "failed", never crash) until you do.

## D-016: Control Center protection is a deny rule on title AND content
Titles can be spoofed or renamed, so the guard denies an action if the focused window title, ANY element name/value in the focused window (address bar URL with Friday's port, approval buttons such as "Allow once"), or the window owning the target element matches the Friday patterns. Pixel actions are refused while any non-minimised Control Center window is visible. Cost: false positives (a page that merely mentions "Friday HUD" is refused). Alternative: title-only denial (rejected, trivially bypassed). Limit: a window that shows none of those markers cannot be recognised.

## D-017: Physical-input approval gate is built but OFF by default (`FRIDAY_REQUIRE_PHYSICAL_INPUT=true` turns it on)
Measured here (`docs/research/injected_input_probe.json`): SendInput, keybd_event and the real Windows-MCP Click and Shortcut were all flagged "injected" by low-level hooks, and physical mouse movement was not. A real physical key/click was NOT observed in my run (nobody pressed during the window), so the physical side is UNVERIFIED until you run the manual test. It defaults off because Remote Desktop, some touch/pen drivers and on-screen keyboards also look injected and would lock you out of approving, and a driver-level injector is not flagged. Alternative: on by default (rejected: could make approvals impossible on some setups).

## D-018: Emergency-stop key kept at Ctrl+Alt+F12
Registration probe on this PC found no collision for it or eight alternatives (`docs/research/hotkey_collision.json`); overlays of NVIDIA, AMD, Steam and SignalRGB cannot be inspected, so those are "unknown". The binding was already configurable (`FRIDAY_STOP_HOTKEY`). Every firing is now logged to `data/logs/estop_triggers.jsonl` with the foreground program and whether the last key was physical or synthetic. If accidental stops keep happening, use `FRIDAY_STOP_HOTKEY=ctrl+alt+shift+f12` (harder to hit by accident, still free here).

## D-019: Benchmarks and scheduled tasks run UNATTENDED (approvals fail closed at once)
`FRIDAY_APPROVAL_MODE=unattended` (benchmark default; `--attended` to opt out): any action that needs approval is denied immediately with `denied:unattended` and the agent is told to choose a safe alternative. Default for normal use stays `attended` (beep + wait up to `FRIDAY_APPROVAL_TIMEOUT`, 120 s). Voice/toast notification is a pluggable hook (`set_attention_hook`), UNVERIFIED. Alternative: wait for a human during benchmarks (rejected: it caused the multi-minute stalls).

## D-020: Dialog handling is context-aware; the button name alone is no longer trusted
Only crash-report, feedback, update-nag and tip dialogs in non-denylisted, non-browser apps are declined automatically, using a vetted decline list ("Don't send", "No thanks", "Remind me later", "Close"...). Save prompts and anything that could discard unsaved work (Don't Save, No, Close, pixel clicks, accelerator keys) always need the owner. Windows-MCP does not expose a dialog's body text (verified with a WinForms dialog), so the window title and the button set are used as evidence; a spoofed title can at worst make a benign dialog look like a save prompt (safe direction). Alternative: let the vision model read the dialog (not built).

## D-021: Experience memory is OFF by default (`FRIDAY_MEMORY=off|record|read|on`)
It records only structured, secret-redacted trajectories (no screenshots, no typed text) locally. Default stays off until the held-out result below justifies turning it on; see the final report for that result. Alternative: record by default (rejected: privacy before evidence).

## D-022: Held-out split is fixed in `friday/bench/splits.py`
Seven tasks (one or two per group) are frozen as held-out; tuning of macros, planner/executor, recovery and memory used only the other 19. Caveat recorded: earlier whole-benchmark diagnostics were not split.

## D-023: Macro layer and planner/executor are OFF by default
They are only switched on by data (see final report). `save_as` / `open_folder` refuse system folders, network shares, `..`, wildcards and env-var paths before any tool call.

## D-024 (2026-10-06) tools-first router default ON
Chosen: ON in product (FRIDAY_TOOLS_FIRST=false disables), OFF in benchmarks. Alternative: off. Writes only NEW plain-text files; outside temp/workspace it asks approval (denied when unattended). Note: it skips opening Notepad visibly.

## D-025 voice pacing default Relaxed
Chosen: Relaxed (old behaviour) until you pick Realtime in Settings or the voice overlay. Alternative: default Realtime.

## D-026 macros stay OFF
The composite multi-line type is always on (no flag); the other macros remain off pending a benchmark.

