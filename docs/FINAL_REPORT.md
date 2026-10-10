# Final report: research-first upgrade (branch `upgrade/research-first`)

Date: 2026-10-06. Nothing was merged or pushed. `docs/CURSOR_BRIEF.md` does not exist in the repo (D-001), so I worked from the message text only.

## Read this first
1. **Keep your hands off the mouse and keyboard during any live benchmark run.** The benchmark drives the real desktop. Pressing Ctrl+Alt+F12 (the emergency stop) ended one hybrid session and made me stop another (see Open risks).
2. The window titles of your Chrome and Cursor windows were minimised by an earlier aborted run. Restore them by hand.
3. Review the whole diff (`git diff main...upgrade/research-first`) before merging.
4. Enable Windows-MCP yourself if you want the desktop agent in the app: set `enabled: true` for `windows` in `config/mcp_servers.yaml` and `AGENT_BACKEND=hybrid` in `.env`. Both are off by default.
5. Run `uv pip install -r requirements/core.lock.txt` in `friday_env` (the lock now uses google-genai; your venv still has the old Gemini package, so the Gemini fallback fails until you do).

## Status by task (PASS = ran and verified; UNVERIFIED = built, not run live)
| Task | Status | Evidence |
|---|---|---|
| Stage A (A1-A7) | PASS | tag `stage-A`; `docs/PROGRESS.md`. Telemetry-off only checked by settings, no network capture: UNVERIFIED |
| B1 e-stop + per-run events + run manager | PASS | tests; live: hotkey halted the real vision loop in 1.41 s (`docs/research/live_estop_check.json`) |
| B2 benchmark harness | PASS | self-test 29/29, 26 tasks. Notepad cleanup kill path UNVERIFIED |
| B3 baseline (legacy, qwen2.5vl) | PASS | 5/78 passed; `bench_baseline_summary.md`; tag `stage-B` |
| C1 hybrid agent | PASS (limited) | 39 unit tests; live run on the real Windows-MCP: 6/26 tasks. First live run exposed a parser bug (0 elements), fixed |
| C2 prompt-injection | PASS offline, UNVERIFIED live | tests with an obedient scripted model; no live injection test was run |
| C3 benchmark comparison | PARTIAL | hybrid 1 rep x 26 tasks (not 3 reps); model comparison on 6 tasks only |
| D1 agentskills loader + trust workflow | PASS | 23 tests |
| D2 voice code | PASS offline | 10 pipeline tests, plumbing check `docs/research/voice_plumbing.json` |
| D2 measurements (Kokoro/Piper/SAPI quality and latency, STT+vision VRAM together, end-to-end latency) | NOT RUN (SKIPPED to cut testing, as you asked) | scripts exist: `scripts/tts_eval.py`, `scripts/voice_plumbing_check.py` |
| D3 real-voice STT accuracy | UNVERIFIED | needs your voice: `docs/VOICE_SAMPLES.md`. `large-v3-turbo` float16 stays provisional. Versions: CTranslate2 4.8.2, cuDNN 9.10.2.21, CUDA 12.8 cuBLAS, driver 617.14 |
| E1 Phase 5 research | PASS | `docs/research/PHASE5_OPTIONS.md`; only a read-only sensor tool built (off by default, live read verified) |
| E2 hardening | PASS offline, CI UNVERIFIED | config validation, JSON logs with run ids, `/health`, atomic writes, google-genai migration, threat model, README/CONTRIBUTING. The CI workflow was never run. Live server start with the new startup check was not run |

## Baseline vs hybrid (same model qwen2.5vl:7b-q4_K_M, ctx 32768, 15 steps, 120 s)
| | Legacy vision loop (3 reps x 26) | Hybrid (1 rep x 26) |
|---|---|---|
| Passed | 5/78 (6%) | 6/26 (23%) |
| Typical wall time per run | 120 s (almost all timeouts) | 7-96 s |
| Mean seconds per step | about 12 | about 5 |

Hybrid passes: notepad_open, calc_open, explorer_open_folder, settings_open, settings_about, settings_display. Legacy passes: notepad_open 1/3, calc_open 2/3, settings_open 2/3. Both fail almost every task that needs typing and saving, multi-step calculator work, Explorer file creation, and (hybrid) every Chrome and canvas page.
Caveats: only 1 rep, so 6/26 vs 5/78 is indicative, not statistically solid. Hybrid prompts were tuned after three smoke runs (D-013); legacy was not. The 9 Chrome/canvas tasks ended after 0-2 steps in 7-20 s; I did not find out why (UNVERIFIED: likely the model answered "fail" or the page was not in the tree). Stage C tag: `stage-C`.

## Model comparison (hybrid agent, 6 tasks, 1 rep: notepad_open, notepad_type_save, calc_open, calc_add, explorer_open_folder, settings_about)
| Model | Passed | Peak VRAM | Notes |
|---|---|---|---|
| qwen2.5vl:7b-q4_K_M | 4/6 (from the 26-task run) | about 9.2-9.3 GB | current benchmark default |
| qwen3-vl:8b-instruct | 4/6 | 12.0-12.4 GB | the `qwen3-vl:8b` tag is the thinking variant; I used `-instruct`. Tools and vision capable |
| qwen3.5:9b | 4/6 | 8.5-12.3 GB | your `.env` default (D-005); has vision, tools, thinking (off here). Two `Type` tool errors |
All three tie. **No default was changed.** UI-TARS-1.5-7B and Fara-7B: NOT TESTED (no verified local serving path found in this run). Six tasks and one rep cannot separate models; treat as "no evidence of a difference".

## Defaults changed
- Code default `VOICE_STT_MODEL` -> `large-v3-turbo` (your `.env` still says `base`, so no effect for you) - D-010.
- `requirements/core.in`: google-generativeai -> google-genai; Gemini model default `gemini-2.5-flash` (guess, `GEMINI_MODEL` overrides) - D-015.
- Config now refuses to start on invalid values - D-014.
- Voice upload capped at 25 MB.
- Nothing else: `AGENT_BACKEND` stays `legacy`, Windows-MCP stays disabled, wake word `hey_jarvis`, barge-in `wake` (D-011).

## Decisions made for you
All in `docs/DECISIONS_NEEDED.md` (D-001 to D-015) with reasoning and the alternative. Highlights: missing brief (D-001), your `.env` default is qwen3.5:9b (D-005), `SHELL_TOOLS_ENABLED=true` in your `.env` left untouched (D-006), benchmarks blank cloud keys (D-007), benchmark-only Settings and trusted-page allowances (D-008), skill approval rules (D-009), timeout 120 s (D-012), prompt tuning (D-013).

## Hard-skipped or not done
- No admin actions, no persistent system setting changes (power plans/audio switching only researched), no real accounts, no money, no PowerShell/Registry tools.
- No pip install into `friday_env` of anything outside the locks; google-genai was checked in a throw-away venv only.
- Kokoro/Piper evaluation, STT VRAM alongside the vision model, end-to-end voice latency: not run.
- UI-TARS / Fara: not tried.
- Custom "hey friday" wake word: not built.
- Live prompt-injection test against the real model: not run.

## Open risks
- Hybrid agent is weak with a 7B model on multi-step tasks (see table); it should not be trusted unattended. Repetition guard added after you saw it repeating (same action 3 times in a row now fails the run).
- The e-stop hotkey fired repeatedly during hybrid benchmark runs (not by me). If it was accidental key presses, benchmarks will keep aborting; if it was deliberate, fine.
- Snapshot parser handles the real format but drops UI elements whose names contain line breaks.
- Windows-MCP is third-party code with your desktop rights (pinned 0.8.7).
- CI never ran; the lock check logic was only tested locally.
- Gemini cloud path untested with a real key.
- Remote access, screen memory: not built, risks in `PHASE5_OPTIONS.md` and `THREAT_MODEL.md`.

## Git
Branch `upgrade/research-first`. Tags: `stage-A`, `stage-B`, `stage-C`, `stage-D`, `stage-E` (D and E tag the current head: their work was committed along the way, see `git log`). Main commits: c28236c (phase 1), d87ec6e (A), 6fc3af0/35cd560 (B1/B2), e03c206 (C1), 8f17fd6 (D1), fae0f76 (D2 code), bb34c39 (E1), 7f00015/490024d (E2), be23c6b (B3), 03efadd/9cd5b4d/ffeb80e (live fixes), 356d59b (C3).

## Manual tests for you (about 30 minutes)
1. `python main.py --server`, open `http://127.0.0.1:8787/health` (should show OK, e-stop registered, audit chain intact). Try `FRIDAY_PORT=abc` and confirm a readable error.
2. Record your voice per `docs/VOICE_SAMPLES.md`, run `scripts/bench_stt_real.py`, decide the STT model.
3. With Windows-MCP enabled and a scratch Notepad file, run `python scripts/hybrid_debug.py "Open Notepad." --max-steps 6` and watch events. Press Ctrl+Alt+F12 once to confirm it stops.
4. Try a hostile page or window title ("ignore previous instructions...") with the hybrid agent in `dry_run` and confirm it refuses.
5. Push the branch and let CI run once; fix whatever it finds.
6. Optional: set a Gemini key, install the new lock, and test the cloud fallback.
