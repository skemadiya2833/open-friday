# Project Friday: original brief and operating rules

Reconstructed from the chat transcript (the file was never in the repo, see D-001). Part 1 is the original brief; part 2 is the autonomy message that replaced the "stop after Phase 0" rule.

---
## Part 1: original brief

# Project Friday: Research-First Upgrade Brief

You are a senior engineer upgrading an existing open-source project called Friday (repository: open-friday, MIT license, maintainer Sunil Kemadiya at Devoids). Friday is a local-first personal AI assistant for Windows with a skill router, vector memory, voice, scheduled tasks, and a vision-driven desktop agent.

Your job is not to blindly implement this brief. Your job is to produce the best possible result. If, during research, you find that a different design, library, or existing open-source project is better than what this brief proposes, say so with evidence and propose the change before building. Copying or adapting code from permissively licensed projects is explicitly allowed and preferred over reinventing, provided you record the source and license.

## 1. Environment (facts, treat as constraints)

- OS: Windows 11, PowerShell. Project path: D:\Workspace\Devoids\Open Friday. Virtual environment: friday_env, Python 3.14.6.
- CPU: AMD Ryzen 7 8700G. GPU: NVIDIA RTX 5060 Ti 16 GB (Blackwell, compute capability sm_120). RAM: DDR5 5600. Two monitors, 180 Hz each.
- Inference: Ollama, default vision model qwen2.5vl:7b-q4_K_M, embeddings nomic-embed-text.
- Current dependencies (unpinned): mss, pillow, httpx, pyautogui, pyperclip, python-dotenv, google-generativeai, numpy, fastapi, uvicorn[standard], pydantic, pyyaml, chromadb, apscheduler, pystray, faster-whisper, pyttsx3, edge-tts, python-multipart.
- Existing structure: friday/{assistant, skills, tools, memory, tasks, voice, server, agent, vision, actions, models, ui}, plus web/. Skills live in friday/skills/builtin/<id>/ as manifest.yaml plus handler.py. Tools are registered in friday/tools/registry.py. The vision loop is friday/agent/loop.py (observe, decide, one action, re-observe).
- The owner prefers a professional tone, no emojis, and honesty over optimism. Do not claim something works unless you ran it.

## 2. Operating rules (apply to every phase)

1. Research before you recommend or install anything. For every new dependency, verify and record in docs/decisions/: the exact PyPI or GitHub name (typosquatting is real), latest release date, license, maintenance status, Windows support, whether a CPython 3.14 Windows wheel exists (check wheel tags, do not assume), and Blackwell (sm_120) compatibility for anything using CUDA. Remember that PyTorch supports Blackwell only from 2.7.0 built for CUDA 12.8 or newer, and that CTranslate2 and ONNX Runtime GPU builds each need their own verification.
2. If a package has no cp314 wheel or is incompatible with Python 3.14, do not downgrade the whole project silently. Choose one of: run it as a separate process in its own uv-managed environment (preferred, communicate over MCP, HTTP, or stdio), or propose standardizing the main environment on a different Python version with evidence. Present the trade-off.
3. Pin versions. Split requirements into core, optional-voice, optional-gpu, and dev. Provide a single documented install path that works from a clean machine, and test it in a fresh virtual environment.
4. Never remove or break existing behavior without a feature flag and a migration note. Keep the existing vision loop working as the fallback.
5. Work in small, reviewable commits. Each phase ends with: what changed, how it was tested, what is unverified, and what you recommend next. Then stop and wait for my approval before starting the next phase.
6. Write tests for new logic. Anything that cannot be automatically tested (live desktop control) gets a documented manual test script with expected results.
7. Default to least privilege. Anything that can execute commands, edit the registry, delete files, send messages, spend money, or touch credentials must be gated, logged, and disabled by default.
8. No telemetry to third parties. If a dependency phones home, disable it by configuration and document it.
9. Use only real information. If you are unsure of an API, read its source or documentation in the installed version, not memory.
10. Keep context small: write plans and findings to files under docs/, and reference them, rather than carrying everything in conversation.

## 3. Reference projects to study first (verify each one is still alive and its license before reusing)

- Windows-MCP by CursorTouch (github.com/CursorTouch/Windows-MCP): MIT, MCP server for Windows desktop control using the UI Automation accessibility tree, optional vision, tools for click, type, scroll, shortcuts, app launch, screenshots per display or region, clipboard, process, file system, PowerShell, registry, and browser page text. It requires Python 3.13 or newer, supports tool exclusion by configuration, and has telemetry on by default. Run it as an isolated subprocess.
- Hermes Agent by Nous Research (github.com/NousResearch/hermes-agent): MIT, skills follow the agentskills.io SKILL.md standard, skill hub, self-improving skills. Windows support is labeled early beta. Study its skill format, approval gating, and skill creation loop. Do not adopt it as the base.
- local-computer-use-agent by Storage1n1 (github.com/Storage1n1/local-computer-use-agent): offline agent using Ollama vision models with Set-of-Marks grounding and crop-and-zoom. Study the grounding approach.
- Microsoft Fara-7B (github.com/microsoft/fara): MIT, small computer-use model built on Qwen2.5-VL-7B, focused on web tasks, with safety checkpoints. Evaluate as a browser sub-agent model and for its safeguard design.
- UI-TARS and UI-TARS-desktop by ByteDance, Agent S (Simular), Cua (cua.ai documentation), OmniParser (Microsoft), GTA1: study grounding and agent architecture. Note that the UI-TARS authors warn that GGUF quantization quality cannot be guaranteed, so benchmark before trusting it.
- Model Context Protocol Python SDK (modelcontextprotocol/python-sdk): use the stable v1.x line. v2 was alpha at the time of writing, so verify the current state.
- openWakeWord (dscripka/openWakeWord): on Windows only the ONNX runtime path is available, so use ONNX models.
- Kokoro-82M (hexgrad/kokoro) and Piper: local TTS candidates. Kokoro needs espeak-ng on Windows and may not support Python 3.14, so verify, and isolate if needed.
- Search for anything newer and better than the above (October 2026). Check GitHub topics for computer-use, gui-agent, windows-automation, local-assistant, and the MCP registry. Report anything that should replace one of these choices.

## 4. Known issues already identified in the code (verify each, then fix or reject with reasoning)

Tool registry (friday/tools/registry.py):
- The workspace sandbox check compares path strings with a prefix test. A sibling folder whose name starts with the workspace name would pass. Replace with a proper resolved-path containment check and add a test that proves the escape case is blocked, including symlinks and drive-letter tricks.
- The risky flag on tools is never enforced in call_tool. There is no approval step. Risky tools (memory delete, shell) currently rely only on a global environment flag.
- Tool parameters are informal strings like "str?" instead of a real schema, and handlers can only return plain text. This blocks images, structured data, error flags, and MCP interoperability.
- The registry is a module-level dictionary filled lazily with no thread safety and no way to register or unregister tools at runtime, which MCP needs.
- start_computer_use is only a text hint, so skill routing and tool routing overlap and can disagree.
- list_files has an unused variable. Search for similar dead code.
- run_shell uses shell=True with a fixed timeout and no allowlist, working directory control, or output redaction.

Computer-use skill and agent loop (friday/skills/builtin/computer_use/handler.py, friday/agent/loop.py):
- The skill blocks the calling thread until the agent finishes, and it subscribes a bridge to a global event bus. With more than one concurrent session, events from different runs can bleed into each other, and only one agent can run at a time. Design a per-run identifier and per-run event channel.
- A global controller is set in both the skill and run_agent. Verify there is no race on cancellation, and that cancel works from both the web UI and a global hotkey.
- The loop is vision-only. Every tick sends a screenshot to a 7B model and produces one action. There is no use of the Windows accessibility tree, no explicit postcondition check, no action risk classification, no persistent action log, and no replay. Success relies on the model re-reading the screen.
- The look-only regex guard in the handler duplicates intent classification already done by the router. Consolidate.
- pyautogui has known limits: DPI scaling and multi-monitor coordinate mapping, and it cannot control windows running with higher privileges than Friday. Test these explicitly and document the results.

Dependencies and config:
- google-generativeai is the legacy Gemini SDK. Google announced its end of support for August 31, 2025. Migrate to the google-genai SDK (verify the current package name and API in installed docs).
- edge-tts uses an online Microsoft service, which contradicts the local-first claim. Keep it only as an explicitly labeled optional cloud voice, and add a fully local default.
- Nothing is pinned, and the project runs on Python 3.14.6, so every transitive wheel is a compatibility risk. Produce a lock file.
- Check whether faster-whisper actually runs on the GPU on this Blackwell card (CUDA 12 and cuDNN 9 libraries, CTranslate2 version) or silently falls back to CPU, and report measured speed.

## 5. Phases

### Phase 0: Audit (no feature code)
Read the entire repository. Produce docs/ARCHITECTURE_AUDIT.md containing: current architecture diagram in text form, the verified status of every item in section 4 (confirmed, rejected, or new), a dependency compatibility matrix for Python 3.14 on Windows, a risk register, and a ranked list of recommended changes with effort and value. Also list any open-source project that already solves a part of Friday better than Friday does, with a recommendation to adopt, adapt, or ignore. Stop and wait.

### Phase 1: Tool layer v2 and MCP client
Redesign the tool layer so that: tools are described with real JSON Schema, results are structured (text, optional images, error flag, metadata), tools can be registered and removed at runtime, every tool has a risk tier (safe, confirm, dangerous), and a central approval service decides, using policy plus a prompt in the Control Center for confirm-tier calls. Add an append-only audit log of every tool call with arguments (with secrets redacted), result summary, duration, and who approved it. Add an MCP client manager that launches configured MCP servers as isolated subprocesses, discovers their tools at startup, and registers them with namespaced names and mapped risk tiers. Configuration lives in a YAML or TOML file, not code. First server to integrate: Windows-MCP, launched through uvx, telemetry disabled, screenshot scale configurable, and the PowerShell and Registry tools excluded by default. Read the real tool list and schemas from the running server, do not hardcode from its README. Fix the sandbox path check and add tests. Provide a Control Center page that shows connected servers, their tools, and a kill switch.

### Phase 2: Hybrid computer use
Make the desktop agent use the accessibility tree first and vision second. Prefer element identifiers over raw pixel coordinates when a tree is available, fall back to vision grounding when it is not (games, canvas apps, custom-drawn UIs). Add a verification step after each action that checks an expected change, and a bounded recovery strategy. Support selecting a display or region so the agent can watch one monitor while the operator uses the other. Keep the existing loop as a selectable fallback behind a flag. Add per-run event channels so concurrent sessions cannot interfere, and make the skill non-blocking. Add a global emergency-stop hotkey, a dry-run mode that narrates without acting, an application allowlist and denylist (password managers, banking, system settings by default), and mandatory confirmation for irreversible actions.

Build a benchmark harness: a fixed suite of 20 to 30 tasks (Notepad, Calculator, File Explorer, Settings, Chrome, a canvas or drawing app, a dialog-heavy installer in a test environment), run each several times, record success, steps, wall time, and VRAM. Compare: the current qwen2.5vl:7b, qwen3-vl:8b, qwen3.5:9b (verify its tags, vision capability, and the tool-call parsing issues reported against it), and, if quality holds up on this hardware, UI-TARS-1.5-7B and Fara-7B served through an OpenAI-compatible endpoint. Report real numbers. Change the default model only if the data supports it. Respect the 16 GB VRAM budget, set an explicit context length of at least 32k for agent use, and let the model manager unload and load models deliberately.

### Phase 3: Skills ecosystem
Add a loader for the agentskills.io SKILL.md format alongside the existing manifest.yaml and handler.py skills, with progressive loading (metadata first, full body on demand). Add a trust workflow for imported skills: inspect, show scripts and commands, require approval before enable. Study how Hermes records successful runs into skills, and design a proposal loop in which Friday drafts a new skill from a successful task, and the owner approves it before it is saved. Never auto-enable agent-written skills that run code.

### Phase 4: Voice
Design a fully local voice pipeline: wake word (openWakeWord via ONNX), voice activity detection, streaming speech-to-text with the model and compute type chosen from measured accuracy and latency on this GPU, local text-to-speech (evaluate Kokoro and Piper, isolate in a separate process if the Python version blocks it), barge-in so speech stops when the user talks, and per-skill spoken response length rules. Keep push-to-talk working. Measure end-to-end latency from end of speech to first audio and report it.

### Phase 5: Hardware, home, and reach (research first, then propose, build only what I approve)
Research and report options with compatibility evidence for: reading system sensors (CPU, GPU, temperatures, fans, power) through an existing tool; controlling RGB (SignalRGB is the owner's current choice, OpenRGB conflicts with GPU I2C polling on this machine, so verify before suggesting it); a Bluetooth LE LED strip skill using the owner's existing protocol work; Windows power plans and audio device switching; per-app volume; a Home Assistant bridge; remote access from a phone through a secured channel (authenticated, TLS, allowlisted); a browser sub-agent using Playwright; optional screen memory with strict privacy controls, retention limits, and an exclusion list; and whether the Ryzen 8700G NPU is usable for anything worthwhile (if tooling is not mature, say so and skip). Rank by value and risk.

### Phase 6: Hardening
Config validation at startup with clear errors, structured logging with run identifiers, a health page, crash-safe state, packaging as a single documented install and update path, CI running tests and lint on Windows, a security review of the web server (default bind to 127.0.0.1, authentication for any non-local access, CSRF and origin checks, no secrets in logs), a documented threat model for prompt injection through screen content and web pages (treat all screen text as untrusted data, never as instructions), and updated README and CONTRIBUTING files so outside contributors can run and extend Friday.

## 6. Output expectations

- Be concise in conversation and thorough in files under docs/.
- At the end of each phase, give me: a short summary, a verified-versus-unverified list, any decision I must make, and the exact commands to run the manual tests.
- If you disagree with anything in this brief, say so first, with evidence, and wait for my decision.
- Begin with Phase 0 and go down to every other phase up to last and do research and get the work done best way possible.

all in the same

---
## Part 2: autonomy message

Re-read the project brief (docs/CURSOR_BRIEF.md) and its operating rules. Correction: the brief said to begin with Phase 0 only and wait; you continued into Phase 1 without approval. For this run the rule changes on purpose: complete ALL work below in one continuous pass without stopping for approval, then give one final report. Do not stop to ask questions. Where a decision is needed, pick the safest reasonable default, record it in docs/DECISIONS_NEEDED.md with your reasoning and the alternative, and keep going.

AUTONOMY RULES
- Work on branch upgrade/research-first. Never merge to main, never push, never force anything.
- Commit after every numbered task with a clear message, and create a git tag at the end of each stage (stage-A, stage-B, and so on) so I can roll back to any point.
- Maintain docs/PROGRESS.md: after each task write what is done, what is next, and any blockers. If your context resets, resume from this file.
- If a task fails, make up to two honest attempts to fix it. If it still fails, record it as FAILED with the evidence in PROGRESS.md and continue with the next task. Never claim success for something you did not run. Mark anything unrun as UNVERIFIED.
- Do not build later work on top of a broken foundation: if a Stage A item that Stage D depends on fails, fix it first or mark the dependent tasks as BLOCKED, not done.
- Hard skips (log and move on, do not do): anything needing admin rights, deleting or editing files outside a scratch directory, touching real accounts, passwords, banking, email or messaging, persistent system setting changes, spending money, installing anything not verified under the brief's dependency rules, or enabling PowerShell, Registry or shell tools outside an isolated test.
- All desktop tests use scratch files and scratch folders only.
- Build and verify the global emergency-stop hotkey BEFORE running any live desktop test or benchmark, and test that it halts a running agent.

STAGE A: Phase 1 acceptance gate
1. Run the real Windows-MCP server through the manager (not direct probing): enable, start, list tools from the live server, one safe-tier call, one confirm-tier call through a real approval, confirm the audit entry. Confirm PowerShell and Registry are excluded, telemetry is off, and the pinned version launches under uv. Save the observed tool names and schemas in docs/research/.
2. Exercise the Tools and MCP page in a real browser if you can drive one (Start, Stop, kill switch, denied and approved approval). If you cannot, say so and write a manual test script.
3. Fresh-venv install on Python 3.14.6 using only documented steps, run tests, start the server. Fix the docs for every failure or workaround.
4. Explain the skipped test; if it covers security behavior, make it run.
5. Approval presence: if polling /api/approvals can cause any approval or skipped prompt without an explicit authenticated human action, redesign it and add a test proving a polling-only script cannot approve anything.
6. Document and test a safe way to run the optional Vite and React shell given the CORS and Origin changes.
7. ADR for the MCP SDK version choice (v2.0.0 stable, v1.x maintenance-only): confirm pin, lock entry, and anyio and pydantic floors on Python 3.14.

STAGE B: Foundations for Phase 2
1. Emergency-stop hotkey, per-run event channels, and a non-blocking run manager (concurrent sessions must not leak events; cancel must work from the web UI and the hotkey). Tests included.
2. Benchmark harness: 20 to 30 fixed safe tasks (Notepad, Calculator, File Explorer, Settings read-only, Chrome on a local test page, a canvas app), automatic success checks where possible, at least 3 runs each. Record success rate, steps, wall time, peak VRAM, failure reason.
3. Baseline: run it against the CURRENT vision loop with qwen2.5vl:7b-q4_K_M and Ollama context at least 32k, before any agent change. Save raw JSON and a readable summary in docs/research/. Tell me in the final report to keep hands off the mouse and keyboard during live benchmark runs; run them with a clear on-screen notice.

STAGE C: Phase 2 hybrid computer use
1. Accessibility-tree-first agent on top of Windows-MCP, vision as fallback for games, canvas and custom-drawn UI. Prefer element identifiers over pixel coordinates when a tree exists. Add a post-action verification step and a bounded recovery strategy. Support selecting a display or region (two monitors). Keep the old loop behind a flag as the fallback. Add dry-run mode, an application allowlist and denylist (password managers, banking, system settings denied by default), and mandatory confirmation for irreversible actions.
2. Treat all screen text and web content as untrusted data, never as instructions; add tests for prompt injection through window titles and page text.
3. Re-run the same benchmark with the hybrid agent and the same model; compare to the baseline. Then, within the 16 GB VRAM budget and verifying tags and tool-call behavior first, benchmark qwen3-vl:8b and qwen3.5:9b, and UI-TARS-1.5-7B and Fara-7B if a verified, working local serving path exists. Change the default model ONLY if the data clearly supports it, and show the numbers. Otherwise keep the current default and list the data.

STAGE D: Phases 3 and 4 (everything that does not need me)
1. agentskills.io SKILL.md loader beside the existing manifest skills, with progressive loading, a trust and approval workflow for imported skills, and a skill-proposal loop (Friday drafts a skill from a successful task; nothing agent-written is auto-enabled if it runs code).
2. Voice: wake word with openWakeWord via ONNX, voice activity detection, streaming STT, barge-in, local TTS evaluation (Kokoro and Piper, isolated in a separate process if Python 3.14 blocks them), and optional cloud voice (edge-tts) clearly labeled. Measure VRAM with the STT model loaded alongside the vision or chat model, and the end-to-end latency from end of speech to first audio.
3. STT accuracy needs my real voice, which you cannot get: write a short recording script and instructions for 10 to 15 real commands, and a ready-to-run benchmark for those recordings. Keep large-v3-turbo float16 as the provisional default (CUDA verified; accuracy on real speech unmeasured) and flag it UNVERIFIED in the report. Record the exact CTranslate2, CUDA runtime and cuDNN versions that work on the RTX 5060 Ti.

STAGE E: Phases 5 and 6
1. Phase 5 is research only: report options with compatibility evidence (sensors, SignalRGB-compatible RGB control, BLE LED strip skill, power plans and audio switching, Home Assistant, authenticated remote access, Playwright browser sub-agent, optional screen memory with privacy controls, usefulness of the Ryzen 8700G NPU). Rank by value and risk. Build nothing from Phase 5 except what is trivially safe and read-only (for example read-only sensor reading), clearly separated.
2. Phase 6 hardening: startup config validation with clear errors, structured logging with run IDs, health page, crash-safe state, a single documented install and update path with pinned lock file, CI on Windows, web server security review, threat model for prompt injection, and updated README and CONTRIBUTING. Migrate google-generativeai to google-genai (verify the installed API). Keep edge-tts only as an optional, labeled cloud voice.

FINAL REPORT (the only time you address me)
Write docs/FINAL_REPORT.md and also print it. Include: for every task, a status of PASS, FAIL, BLOCKED, SKIPPED or UNVERIFIED with evidence; the baseline versus hybrid benchmark table and the model comparison table with real numbers; every default you changed and why; every decision you had to make for me (from DECISIONS_NEEDED.md) with the alternative; every hard-skipped action; open risks; the git tags and commit list; the exact manual tests I must run myself; and a list of anything that I must do by hand (record voice samples, enable Windows-MCP in config, review the diff before merging).
