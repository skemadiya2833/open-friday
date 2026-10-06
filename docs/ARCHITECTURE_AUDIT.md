# Friday architecture audit (Phase 0)

Date of audit: 2026-10-06. Branch: `upgrade/research-first` (from `main` @ `74d3fb9`).
Method: full read of `friday/` core modules, executed probes on this machine, and live PyPI/GitHub/Ollama
queries (raw data in `docs/decisions/*.json`, `docs/research/`). Anything not run is marked **unverified**.

Scope note: the brief asks to stop after each phase for approval; the owner's last instruction was to run all
phases in one pass. Decisions that deviate from the brief are recorded as ADRs in `docs/decisions/` so they can
be reverted cheaply.

---------------------------------------------------------------------------------------------------------

## 1. Environment facts (measured, not assumed)

| Item | Measured value | Source |
|---|---|---|
| Python in `friday_env` | 3.14.6 | `friday_env\Scripts\python.exe --version` |
| Python used to run the server in earlier sessions | **3.12.10** (system `python`) | traceback paths `Python312\Lib\...` |
| Python launcher | 3.14 and 3.12 installed | `py -0p` |
| `uv` / `uvx` | not installed originally; `uv 0.12.23` now installed into `friday_env` | `uv --version` |
| GPU | RTX 5060 Ti 16311 MiB, compute_cap 12.0, driver 617.14 | `nvidia-smi` |
| CUDA toolkit on PATH | 12.8 (cublas64_12, cudart64_12); **no cuDNN 9 on PATH** | `where.exe` |
| Displays | 2 x 1920x1080 at x=0 and x=1920; primary = monitor 1 | `mss.monitors`, `GetSystemMetrics` |
| Ollama | 0.30.10 (update to 0.35.1 available) | `ollama --version` |
| Installed models | qwen3.5:9b, qwen3.5:4b, qwen2.5vl:7b-q4_K_M, nomic-embed-text, qwen3-coder:30b | `ollama list` |
| Baseline tests | 8 passed (3.14 env) | `pytest -q` |
| Baseline lint | 15 `ruff --select F` findings (14 unused imports, 1 unused variable) | `ruff check` |

Important discrepancy: the brief says the project runs on 3.14.6; sessions in this repo were actually served by
3.12.10. Both interpreters import all core modules (checked on 3.14). The install path must pick one explicitly
(see ADR-0003).

## 2. Current architecture (text diagram)

```
                       +--------------------+        +----------------------+
 Browser UI (web/public) <--HTTP/SSE/WS-->  | FastAPI (server/app) |  <-- tray / tkinter UI (ui/)
                       +---------+----------+        +----------+-----------+
                                 |                              |
                      assistant/orchestrator  <----- tasks/scheduler (APScheduler + sqlite)
                                 |
                  intent.classify_intent (rules + LLM + policy)  -> skills/router (legacy shim)
                                 |
              +------------------+--------------------------------------------+
              |   skills/builtin/{chat,files,memory,observe,research,tasks,computer_use}
              |        |                 |
              |   tools/react.py    computer_use/handler.py  (blocks calling thread, global event bus bridge)
              |        |                 |
              |   tools/registry.py   agent/loop.py  observe -> decide -> ONE action -> re-observe
              |   (module dict)        |      vision/feed (mss) -> agent/planner -> models/local (Ollama /api/chat)
              |                        |      actions/executor (pyautogui, aim_verify, RUN_SHELL)  safety/gate
              +------------------------+--------------------------------------------+
   memory/ (Chroma + nomic-embed-text)   voice/stt (faster-whisper CPU int8)  voice/tts (edge-tts -> ffmpeg -> pyttsx3)
   models/manager (load/unload Ollama)   models/cloud (google-generativeai fallback)  ui/events (GLOBAL EventBus)
   agent/control (GLOBAL controller)
```

Process model: one Python process. Agent runs on a thread; `computer_use` skill joins that thread, so one HTTP
worker thread is held for the whole run. Global singletons: `EventBus`, `AgentController`, tool dict, skill
registry, model manager, memory, scheduler.

## 3. Reference projects: verified status (GitHub API, 2026-10-06)

| Project | License | Last push | Latest release | Verdict |
|---|---|---|---|---|
| CursorTouch/Windows-MCP | MIT | 2026-10-06 | v0.8.7 (2026-09-30) | **Adopt** as isolated MCP server (Phase 1) |
| microsoft/UFO | MIT | 2026-10-06 | v3.0.10 (2026-09-22) | **Study**: hybrid UIA + vision Windows agent, closest to Phase 2 design. Not adopted: large framework, own agent loop |
| trycua/cua | MIT | 2026-10-06 | cua-sdk-v0.4.1 | Study (sandboxed VM approach); ignore for now |
| NousResearch/hermes-agent | MIT | 2026-10-06 | v2026.9.24 | **Study** skill format/approval; do not adopt as base |
| agentskills/agentskills | Apache-2.0 (docs CC-BY-4.0) | 2026-08-09 | none | **Adopt** SKILL.md format (Phase 3) |
| modelcontextprotocol/python-sdk | MIT | 2026-10-05 | **v2.3.0 (2026-10-02)** | **Adopt 2.x**, contradicting brief (ADR-0001) |
| microsoft/fara | MIT | 2026-09-22 | none | Evaluate as browser model only if servable; see Phase 2 |
| bytedance/UI-TARS, UI-TARS-desktop | Apache-2.0 | 2026-01-27 / 2026-10-05 | v0.3.0 | Study grounding; model benchmarked only if Ollama build is usable |
| simular-ai/Agent-S | Apache-2.0 | 2026-09-05 | v0.3.2 | Study |
| microsoft/OmniParser | repo CC-BY-4.0 (model weights have separate licenses: **verify before use**) | 2026-07-20 | v.2.0.1 | Ignore (heavy, license caveat) |
| Storage1n1/local-computer-use-agent | MIT | 2026-09-17 | none | 0 stars, tiny; study SoM idea only |
| dscripka/openWakeWord | Apache-2.0 | 2025-12-30 | v0.6.0 (**2024-02**) | Adopt ONNX path (Phase 4); release is old, flag as risk |
| hexgrad/kokoro | Apache-2.0 | 2025-08-06 | none | Isolate: PyPI `kokoro` requires Python <3.13 |
| OHF-Voice/piper1-gpl (piper-tts) | **GPL-3.0** | 2026-09-28 | v1.8.0 | Separate process only (license) |
| rhasspy/piper (original) | MIT | **archived** | 2023 | Do not use |
| SYSTRAN/faster-whisper | MIT | 2026-10-05 | v1.2.1 (2025-10) | Keep |
| snakers4/silero-vad | MIT | 2026-09-29 | v6.2.3 | Adopt for VAD (ONNX) |
| microsoft/playwright-python / playwright-mcp | Apache-2.0 | 2026-10-05 / 09-28 | 1.63.0 / 0.0.83 | Adopt for browser sub-agent (Phase 5 proposal) |
| browser-use/browser-use | MIT | 2026-10-03 | 0.13.10 | Study; heavier than needed |
| Yan-Labs/GTA1 | - | - | - | **404**: repository name in the brief is wrong or moved; not evaluated |
| OpenRGB/OpenRGB | - | - | - | **404 on GitHub** (project is hosted on GitLab); not evaluated here |

Evidence file: `docs/decisions/github_audit.json`; matrix: `docs/decisions/DEPENDENCY_MATRIX.md`.

## 4. Verification of every item in section 4 of the brief

Legend: CONFIRMED (reproduced or read in code), REJECTED, PARTIAL, NEW (found during audit).

### 4.1 Tool registry (`friday/tools/registry.py`)

| # | Claim | Status | Evidence |
|---|---|---|---|
| T1 | Sandbox uses string-prefix check | **CONFIRMED, reproduced** | `_safe_workspace_path` uses `str(target).startswith(str(root))`. With a sibling folder `workspace_evil`, `read_file ../workspace_evil/secret.txt` returned `TOP SECRET` and `write_file` created a file outside the workspace (executed on a temp data dir). |
| T2 | `risky` flag never enforced | **CONFIRMED** | `call_tool` calls `tool.handler` directly; `risky` is read nowhere. `memory_delete` has no gate at all; `run_shell` is gated only by `SHELL_TOOLS_ENABLED`. |
| T3 | Informal parameter strings, text-only results | **CONFIRMED** | `{"query": "str", "limit": "int?"}`; handlers return `str`; `react.py` truncates to 1000/2000 chars. |
| T4 | Module-level dict, lazy fill, no lock, no runtime (un)register | **CONFIRMED** | `_TOOLS` filled on first `get_tool`; no lock; no `register`/`unregister` API. |
| T5 | `start_computer_use` only a text hint | **CONFIRMED** | `_start_computer_use` returns a sentence; skill router and tool path can disagree. |
| T6 | `list_files` unused variable | **CONFIRMED** | `root = Path(WORKSPACE_DIR)` assigned and unused (ruff F841, `registry.py:85`). |
| T7 | Similar dead code | **CONFIRMED** | 14 unused imports, e.g. `scheduler.py` (json, timedelta, Path, CronTrigger, DateTrigger), `server/app.py` (asyncio, FileResponse, Field), `executor.py` (hide_aim_cursor), `skills/base.py` (AsyncIterator), `ui/capture.py`, `ui/tray.py`, `ui/app.py`. |
| T8 | `run_shell`: `shell=True`, fixed timeout, no allowlist/cwd/redaction | **CONFIRMED** | `registry.py:186`. Also duplicated separately in `actions/executor.py` (`RUN_SHELL`, line ~473) with its own gate. |
| T9 (NEW) | **Two independent shell paths with different gating** | NEW | Tool `run_shell` (env flag only) vs agent action `RUN_SHELL` (flag + `RISKY_ACTIONS` approval). |
| T10 (NEW) | `react.py` tool-call parser executes whatever JSON the model emits, including from untrusted screen/web text pulled into prompts | NEW | `react.py:_extract_tool_call` -> `call_tool` with no policy layer. Prompt injection risk. |

### 4.2 Computer-use skill and agent loop

| # | Claim | Status | Evidence |
|---|---|---|---|
| C1 | Skill blocks calling thread; global bus bridge; concurrent sessions bleed events; only one agent at a time | **CONFIRMED** | `handler.py`: `thread.start(); thread.join()`. `bus.subscribe_all(_bridge)` on the process-wide `EventBus`; every `emit()` from any run reaches every subscriber. `_active` controller is a single global, so a second run would overwrite the first. |
| C2 | Global controller race on cancel | **CONFIRMED (race)** | `set_controller` is called in the skill's `_run`, again in `run_agent`, and cleared in both `finally` blocks. A run that ends clears the global even if a newer run replaced it, losing cancel for the newer run. `request_cancel` also closes httpx clients while the model thread may be mid-stream (benign but unsynchronised). |
| C3 | Cancel from web UI and global hotkey | **PARTIAL** | Web: `POST /api/agent/cancel` exists. **No global hotkey exists** (grep for hotkey libs: none). Only `pyautogui.FAILSAFE = True` (move mouse to a corner). |
| C4 | Vision-only loop, no accessibility tree, no postcondition check, no risk classification, no action log/replay | **CONFIRMED** | `loop.py`/`planner.py`: each tick = screenshot -> VLM -> one action. `RISKY_ACTIONS` is a fixed name set + model-provided `risky` boolean. Only in-memory `session.history`. |
| C5 | Look-only regex guard duplicates router | **CONFIRMED** | `handler.py:_LOOK_ONLY` vs `assistant/intent.py` policy layer. To be removed in Phase 2 in favor of intent policy. |
| C6 | pyautogui DPI / multi-monitor / elevated windows | **PARTIAL - measured what is possible** | See 4.4. DPI awareness is only set in `ui/capture.py` (legacy overlay path), not in the capture/executor path. `PRIMARY_MONITOR_INDEX=1` hard-coded: on this machine monitor 1 is the primary, which holds, but there is no selection of other displays. Elevated-window limitation (UIPI) is a documented Windows behavior and is **unverified here** (needs an elevated test app; manual script provided in Phase 2). |
| C7 (NEW) | Default `MODEL_NUM_CTX=8192` for the agent | NEW | `config.py:47`; brief requires >=32k for agent use. qwen3.5:9b advertises 262144 ctx; VRAM cost must be measured. |
| C8 (NEW) | The earlier session's `Image is not JSON serializable` crash came from bridging `live_frame` PIL objects into SSE | FIXED earlier in this repo | Sanitizer in `handler.py` + `server/app.py`; to be replaced by per-run channels. |

### 4.3 Dependencies and config

| # | Claim | Status | Evidence |
|---|---|---|---|
| D1 | `google-generativeai` is legacy/EOL | **CONFIRMED** | PyPI 0.8.6 (2025-12-16) is the last release; `google-genai` 2.28.0 (2026-10-02) is current, Apache-2.0, py3-none-any. Used only in `models/cloud.py`. Migrate (Phase 6/ADR-0005). |
| D2 | edge-tts is an online service, contradicts local-first | **CONFIRMED** | `voice/tts.py` calls `edge_tts.Communicate`; it is the *first* option tried. Make it opt-in cloud voice; default local (Phase 4). |
| D3 | Nothing pinned; no lock | **CONFIRMED** | `requirements.txt` has 19 bare names. Will produce `requirements/*.in` + locked `requirements/*.txt` (Phase 6). |
| D4 | faster-whisper may silently fall back to CPU on Blackwell | **PARTIAL / worse: it is hard-coded to CPU** | `voice/stt.py`: `WhisperModel(VOICE_STT_MODEL, device="cpu", compute_type="int8")`, model default `base`. CTranslate2 4.8.2 does see the GPU (`get_cuda_device_count()==1`, float16/int8_float16/bfloat16 supported). Measured speeds: section 5. |
| D5 (NEW) | `mss.mss` is deprecated in mss 10.2.0 (use `mss.MSS`) | NEW | DeprecationWarning observed. Used in `vision/feed.py`. |
| D6 (NEW) | Server CORS: `allow_origins=["*"]` with `allow_credentials=True`, **no authentication**, WebSocket origin unchecked | NEW, **high severity** | `server/app.py:21-28`. Any web page open in the user's browser can call `http://127.0.0.1:8787/api/chat` (and every other route) and make Friday drive the desktop. DNS-rebinding is also unmitigated (no Host check). Fixed in Phase 6. |
| D7 (NEW) | `PATCH /api/skills/{id}` and `POST /api/skills/{id}/enabled` rewrite `manifest.yaml` on disk through unauthenticated routes | NEW | `skills/registry.py`. |
| D8 (NEW) | Skill loader imports `friday.skills.builtin.<folder>.handler` only | NEW | External skills folders cannot load; Phase 3 needs a separate, sandboxed loader. |
| D9 (NEW) | `chromadb` telemetry already disabled | OK | `memory/__init__.py:115` `Settings(anonymized_telemetry=False)`. HF telemetry disabled in `stt.py`. |
| D10 (NEW) | Server was served by 3.12 while env is 3.14 | NEW | See section 1. |

### 4.4 Measurements

DPI/monitors (this machine): two 1920x1080 displays, primary at (0,0); mss monitor 0 is the 3840x1080 union.
At 100 % scaling (observed) pyautogui and mss coordinates agree for the primary; behavior at 125/150 % and on the
secondary display is **unverified** (cannot change user display settings in an unattended run). Phase 2 adds
explicit display selection and a DPI self-test (`scripts/dpi_selftest.py`) for the owner to run.

STT benchmark: see `docs/research/stt_bench.json` and section 5.

## 5. faster-whisper on Blackwell (measured)

Run: `scripts/bench_stt.py`, CTranslate2 4.8.2, faster-whisper 1.2.1, CUDA 12.8 runtime libraries from the
installed toolkit, `friday_env` (Python 3.14.6). Sample: 10.2 s of English speech synthesized locally with
Windows SAPI (no network), `beam_size=1`, best of 3 runs after a warm-up. Raw data:
`docs/research/stt_bench.json`.

| Model | Device / compute | Load (s) | Decode 10.2 s audio (s) | Real-time factor | VRAM added |
|---|---|---|---|---|---|
| base | CPU int8 (current code path) | 1.5 | 0.50 | 0.049 | - |
| base | CUDA float16 | 0.6 | 0.12 | 0.012 | not measured |
| small | CPU int8 | 48.9 (includes first-time model load) | 1.51 | 0.148 | - |
| small | CUDA float16 | 1.2 | 0.20 | 0.020 | not measured |
| large-v3-turbo | CPU int8 | 145 (includes download) | 5.51 | 0.542 | - |
| large-v3-turbo | CUDA float16 | 2.2 | 0.24 | 0.023 | ~2.2 GB |
| large-v3-turbo | CUDA int8_float16 | 3.0 | 0.23 | 0.022 | ~1.2 GB |

Conclusions (measured):
* The GPU path **does work on this Blackwell card** with CTranslate2 4.8.2: no silent CPU fallback occurred;
  asking for `cuda` either ran on the GPU or raised. A cuDNN 9 DLL was not on `PATH` and was not needed here.
* The shipped configuration (CPU int8, model `base`) is already fast (RTF 0.05). The bigger win is accuracy: on
  GPU, `large-v3-turbo` decodes in ~0.23 s for 10 s of speech, 24x faster than on CPU, for ~1.2 GB VRAM with
  `int8_float16`. That fits next to a 6-7 GB vision model on 16 GB.
* Caveat: WER was identical (0.062, one token: "3.30" vs "three thirty", i.e. normalisation, not recognition)
  across all models because a single clean synthetic voice does not discriminate between models. Accuracy
  ranking is **unverified**; Phase 4 includes a harness to compare on recorded owner speech.

## 6. Dependency compatibility (Python 3.14 / Windows x64)

Full table: `docs/decisions/DEPENDENCY_MATRIX.md` (60 packages, tag-derived). Findings that change decisions:

| Finding | Consequence |
|---|---|
| `mcp` 2.3.0 is stable (2.0.0 on 2026-07-28, five minor releases since). Brief said "use stable 1.x". | Use `mcp>=2.3,<3` (ADR-0001). Installed and verified: `from mcp import Client, StdioServerParameters`. |
| `windows-mcp` 0.8.7 declares `requires-python >=3.14` (README badge says 3.13+). Needs `fastmcp>=3`, `posthog` (telemetry). | Run isolated via `uv tool run --python 3.14` (done, 18 tools listed). Pin `==0.8.7`. |
| `kokoro` requires Python <3.13, `kokoro-onnx` <3.14, `misaki` <3.13 | Kokoro must run in a separate uv env on 3.12 (ADR-0004). |
| `piper-tts` is GPL-3.0-or-later; original rhasspy/piper archived | Piper only as an external process; never imported in-process (MIT project). |
| `webrtcvad` (2017), `pyaudio`: no cp314 wheel | Use `sounddevice` + `silero-vad` (ONNX). |
| `openwakeword` last PyPI release 2024-02 | Works only through ONNX on Windows; treat as maintenance risk; wake word is optional. |
| `pyautogui` 0.9.54 is sdist-only and unmaintained since 2023 | Keep for the fallback loop only; new path goes through Windows-MCP. |
| `homeassistant-api` is GPL | Use plain REST via `httpx` instead. |
| `keyboard` unmaintained since 2020 | Use Win32 `RegisterHotKey` via `ctypes` for the emergency stop; no dependency. |
| `torch` 2.14.1 has cp314 win wheel | Not needed in core. Only if a GPU TTS/VAD is selected later. |
| `onnxruntime-gpu` 1.30.0 cp314 wheel exists | Blackwell/CUDA support **unverified**; not needed since VAD/wake-word run on CPU. |

## 7. Risk register

| ID | Risk | Likelihood | Impact | Mitigation | Phase |
|---|---|---|---|---|---|
| R1 | Cross-origin web page drives the desktop through unauthenticated API (D6) | High | Critical | Origin/Host checks, bearer token for non-local, remove CORS `*` | 6 (partial in 1) |
| R2 | Workspace sandbox escape (T1) | High | High | `Path.relative_to` containment + tests | 1 |
| R3 | Prompt injection through screen/web text reaching tool calls (T10) | Medium | High | Untrusted-content framing, tier-gated tools, approval for confirm/dangerous | 1, 6 |
| R4 | Concurrent run event bleed / lost cancel (C1, C2) | Medium | Medium | Per-run id + channel, controller registry | 2 |
| R5 | MCP server executes arbitrary commands (Windows-MCP PowerShell/Registry/FileSystem/Process) | Medium | Critical | Exclude by default; risk tiers; approval; audit log | 1 |
| R6 | Windows-MCP telemetry (PostHog on by default) | Certain unless disabled | Privacy | `ANONYMIZED_TELEMETRY=false` forced by the manager; documented | 1 |
| R7 | Python 3.14 wheel gaps for future deps | Medium | Medium | Isolate via uv; lock file | 6 |
| R8 | Agent-written skills run code | Medium | High | Never auto-enable; trust workflow | 3 |
| R9 | `edge-tts` sends all spoken text to Microsoft | Certain when enabled | Privacy | Opt-in only | 4 |
| R10 | openWakeWord unmaintained | Medium | Low | Optional; push-to-talk remains | 4 |
| R11 | Upstream MCP server API drift (Windows-MCP pre-1.0) | Medium | Medium | Pin versions; discovery at startup; schema-driven | 1 |
| R12 | VRAM contention (VLM + Whisper + TTS on 16 GB) | Medium | Medium | Model manager; STT on CPU or small GPU model; measured below | 2, 4 |

## 8. Ranked recommendations (value / effort)

| Rank | Change | Value | Effort |
|---|---|---|---|
| 1 | Server hardening: remove CORS `*`, Host/Origin checks, token for non-local (D6) | Critical | S |
| 2 | Tool layer v2 (schema, structured results, tiers, approval, audit) + sandbox fix | High | M |
| 3 | MCP client manager + Windows-MCP (a11y tree + multi-display) | High | M |
| 4 | Per-run event channels, non-blocking skill, emergency-stop hotkey | High | M |
| 5 | Accessibility-first hybrid agent with postconditions | High | L |
| 6 | Pin/lock dependencies, split requirements, one install path | Medium-High | S |
| 7 | STT: GPU when it measurably wins; local default TTS | Medium | M |
| 8 | SKILL.md loader + trust workflow | Medium | M |
| 9 | google-genai migration | Low-Medium | S |
| 10 | Research-only items of Phase 5 | n/a | S |

## 9. Open-source projects that already do parts better than Friday

| Friday component | Better existing option | Recommendation |
|---|---|---|
| Desktop control (pyautogui + screenshots) | Windows-MCP (UIA tree, element ids, multi-display, WaitFor) | **Adopt** (isolated) |
| Skill format | agentskills.io SKILL.md | **Adopt** alongside manifest.yaml |
| Hybrid UIA + vision agent design | microsoft/UFO | **Study**, ignore as dependency |
| MCP client | official `mcp` SDK 2.x | **Adopt** |
| VAD | silero-vad | **Adopt** |
| Browser sub-agent | Playwright / playwright-mcp | **Adopt** (propose, Phase 5) |
| Web automation model | browser-use | Ignore (heavy) |
