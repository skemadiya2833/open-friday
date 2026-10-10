# Project Friday

Local-first personal AI assistant with **Hermes-inspired skills**, vector memory, voice, scheduled tasks, and a vision-driven desktop agent (default **`qwen3.5:9b`** on this stack; see [`docs/CONTINUE.md`](docs/CONTINUE.md)).

Talk to Friday. It picks the best skill for the job — chat, research, memory, files, tasks, or **computer use** (watch the screen → one action → re-observe).

---

## Quick start

Requires Windows 11, Python 3.14 (tested on 3.14.6), and [Ollama](https://ollama.com).

```powershell
# Use already-installed Ollama models (do not pull unless the owner asks):
#   qwen3.5:9b (default), qwen3.5:4b, qwen3-vl:8b-instruct,
#   qwen2.5vl:7b-q4_K_M, nomic-embed-text, qwen3-coder:30b

python -m venv friday_env
friday_env\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements/core.lock.txt          # pinned, tested set
copy .env.example .env

python main.py              # tray + Control Center
# or
python main.py --server     # http://127.0.0.1:8787/  (loopback until phone hostname is set)
```

Optional extras (each is a separate pinned lock file):

| Need | Command |
|------|---------|
| Voice (faster-whisper STT, edge-tts cloud voice) | `pip install -r requirements/voice.lock.txt` |
| Development and tests | `pip install -r requirements/dev.lock.txt` then `pytest` |
| Windows-MCP desktop tools | `uv` must be on PATH or in the venv's `Scripts` folder (`pip install uv`, not covered by the lock files); enable the `windows` server in `config/mcp_servers.yaml` |

GPU speech-to-text additionally needs a CUDA 12 runtime (cuBLAS) visible on `PATH`; see `docs/research/stt_bench.json`.
Lock files are generated with
`uv pip compile requirements/core.in --python-version 3.14 --python-platform windows -o requirements/core.lock.txt`.
This path was verified in a fresh Python 3.14.6 venv (76 tests pass, server starts); `voice.lock.txt` was not installed in that test.

### Security defaults

- **Passkey device auth** (`FRIDAY_AUTH=local` by default): loopback only until a registrable hostname + trusted cert are configured (`FRIDAY_AUTH=remote` + `FRIDAY_PUBLIC_HOST`). See [`docs/PHONE_SETUP.md`](docs/PHONE_SETUP.md). Phones cannot use passkeys against raw LAN IPs or `.local` names.
- Request guard: exact Host/Origin allow-list (no private-IP Host relaxation). `FRIDAY_API_TOKEN` remains an optional script fallback only.
- Tools run through a policy gate (`config/policy.yaml`): safe tools run, confirm tools ask in the UI, dangerous tools are denied. Every call is written to a hash-chained audit log. `SHELL_TOOLS_ENABLED` defaults to **false**.
- MCP servers (`config/mcp_servers.yaml`) are disabled by default; PowerShell and Registry tools are excluded.
- There is **no CI**. Before any push: `python scripts/pre_push_secrets_check.py` and `pytest` locally.

### Optional React shell (Vite)

The default UI in `web/public` needs no build. To use the Vite dev shell, the backend must trust its origin (the Vite proxy rewrites `Host` but keeps the browser `Origin`):

```powershell
$env:FRIDAY_ALLOWED_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"
python main.py --server
cd web; npm install --ignore-scripts; npm run dev     # open http://localhost:5173
```

Do not set `FRIDAY_ALLOWED_ORIGINS` to anything you do not control. The React shell does not yet show approval prompts; approvals are answered in the default UI.

Legacy modes: `python main.py --gui` (tkinter) · `python main.py --cli "Open Notepad"`

---

## What you get

| Surface | Purpose |
|---------|---------|
| **Chat** | Conversational assistant with session continuity |
| **Skills** | Auto-routed packs: chat, computer_use, research, memory, files, tasks |
| **Memory** | Chroma vector DB — searchable, UI-managed |
| **Tasks** | One-shot + cron jobs via APScheduler |
| **Voice** | Push-to-talk STT (faster-whisper) + local TTS (Piper / pyttsx3) |
| **Computer use** | Existing vision observe → decide → act loop |

```
You → Control Center → SkillRouter → Skill
                              ↓
                     computer_use → vision loop
                     research/memory/files/tasks → tools (ReAct-lite)
                     chat → local LLM
```

---

## Install, update, check

One supported path: pinned lock files (see Quick start). To update, change a `requirements/*.in` file, re-run `uv pip compile` (command above), review the lock diff, then `uv pip install -r requirements/core.lock.txt` (add `voice` / `dev` locks as needed). Never `pip install <package>` ad hoc. Before any push, run `python scripts/pre_push_secrets_check.py` (there is no CI).

- Startup validates your configuration and stops with a readable message for bad values (`friday/diagnostics.py`).
- Health page: `http://127.0.0.1:8787/health` (JSON: `/api/health/detail`): config issues, Ollama, audit-chain check, e-stop hotkey, MCP servers, disk.
- Logs: `data/logs/friday.jsonl` (JSON lines, each tagged with the agent run id; secrets redacted). Audit log: `data/audit/`.
- Emergency stop: **Ctrl+Alt+F12** halts agent runs and revokes approvals.

## Desktop agent backends

`AGENT_BACKEND=legacy` (default) is the original screenshot loop. `AGENT_BACKEND=hybrid` reads the Windows accessibility tree through Windows-MCP first and falls back to vision; it verifies each action, refuses sensitive apps by default and asks before irreversible steps. Enable the `windows` server in `config/mcp_servers.yaml` first. Benchmark: `python -m friday.bench.run --backend hybrid --help`. **Keep your hands off the mouse and keyboard while a live benchmark runs.** Results and model comparison: `docs/FINAL_REPORT.md`.

## Resume / optimization state

**Start here after a break:** [`docs/CONTINUE.md`](docs/CONTINUE.md) — current model/VRAM profile, what is optimized, what is still open, and how to pick up the branch.

Also: [`docs/PROGRESS.md`](docs/PROGRESS.md) (full task log) · [`docs/DECISIONS_NEEDED.md`](docs/DECISIONS_NEEDED.md) · [`docs/FINAL_REPORT.md`](docs/FINAL_REPORT.md) · [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md) · [`docs/research/PHASE5_OPTIONS.md`](docs/research/PHASE5_OPTIONS.md)

### Current optimization snapshot (2026-10-10)

- **Model:** `qwen3.5:9b` default (unified on 16 GB). Role map opt-in (`FRIDAY_MODEL_ROLES`); see [`docs/research/MODEL_ROLES.md`](docs/research/MODEL_ROLES.md). Thinking off unless deep mode.
- **Auth / phone:** passkeys; remote off until hostname (PHONE_SETUP). Loopback default.
- **Agent:** loop breaker, stall recovery, plan-before-act on multi-step, tools-first. Hybrid opt-in.
- **Persona:** [`docs/PERSONA.md`](docs/PERSONA.md) — calm, dry, address as boss; humor off/dry/full.
- **Voice:** Realtime + barge-in. Phone mic needs a trusted HTTPS hostname (not raw IP for passkeys).
- **Research:** one HTTP fetch + briefing; no Google tab spam.

---

## Skills

Skills live in `friday/skills/builtin/<id>/` with `manifest.yaml` + `handler.py`.

The **SkillRouter** scores each enabled skill using:

1. Embedding similarity to the skill description  
2. Keyword / trigger matches  
3. Vision hints (`open`, `notepad`, `click`, …)  
4. Priority tie-break  

You can override the skill from the UI (Auto skill dropdown) or disable packs on the Skills page.

---

## Architecture

```
friday/
├── assistant/      # Sessions, orchestrator
├── skills/         # Registry, router, builtin packs
├── tools/          # Tool registry + ReAct-lite
├── memory/         # Chroma vector store
├── tasks/          # Scheduler
├── voice/          # STT / TTS
├── server/         # FastAPI Control Center API
├── agent/          # Vision observe → decide → act
├── vision/         # Live screen feed
├── actions/        # Mouse/keyboard executor
├── models/         # Ollama client + ModelManager
└── ui/             # Overlay, tray, legacy tkinter
web/
├── public/         # Default Control Center (no npm required)
└── src/            # Optional Vite + React shell
```

---

## Hardware notes (RTX 5060 Ti 16GB)

- Vision model ~6 GB Q4 — stays fully on GPU  
- Embeddings via `nomic-embed-text` (CPU-friendly)  
- `ModelManager` avoids loading two large GPU models at once  
- Optional `CHAT_MODEL` if you pull a separate instruct model  

---

## Configuration

See [`.env.example`](.env.example). Important keys:

| Variable | Default | Meaning |
|----------|---------|---------|
| `MODEL` / `VISION_MODEL` / `CHAT_MODEL` | `qwen3.5:9b` | Unified default |
| `EMBED_MODEL` | `nomic-embed-text` | Vector memory |
| `FRIDAY_AUTH` | `local` | `off` / `local` / `remote` |
| `FRIDAY_HOST` | `127.0.0.1` | Loopback until remote hostname |
| `FRIDAY_PORT` | `8787` | Control Center |
| `FRIDAY_HUMOR` | `dry` | `off` / `dry` / `full` |
| `VOICE_ENABLED` | `true` | Mic / speak APIs |
| `SHELL_TOOLS_ENABLED` | `false` | Gate `run_shell` |

---

## Contributing

Friday needs contributors — see [CONTRIBUTING.md](CONTRIBUTING.md).

Maintainer: **Sunil Kemadiya**, CEO at [Devoids - IT Solutions](https://devoids.in)  
Contact: [skemadiya@gmail.com](mailto:skemadiya@gmail.com)

---

## License

MIT License.
