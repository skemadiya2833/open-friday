# Project Friday

Local-first personal AI assistant with **Hermes-inspired skills**, vector memory, voice, scheduled tasks, and a vision-driven desktop agent (**qwen2.5vl:7b-q4_K_M**).

Talk to Friday. It picks the best skill for the job — chat, research, memory, files, tasks, or **computer use** (watch the screen → one action → re-observe).

---

## Quick start

Requires Windows 11, Python 3.14 (tested on 3.14.6), and [Ollama](https://ollama.com).

```powershell
ollama pull qwen2.5vl:7b-q4_K_M
ollama pull nomic-embed-text

python -m venv friday_env
friday_env\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements/core.lock.txt          # pinned, tested set
copy .env.example .env

python main.py              # tray + Control Center
# or
python main.py --server     # http://127.0.0.1:8787/
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

- The server listens on `127.0.0.1` only and rejects foreign `Host` and `Origin` headers; there is no CORS. Binding to any other address is refused unless `FRIDAY_API_TOKEN` is set.
- Tools run through a policy gate (`config/policy.yaml`): safe tools run, confirm tools ask in the UI, dangerous tools are denied. Every call is written to a hash-chained audit log.
- MCP servers (`config/mcp_servers.yaml`) are disabled by default; PowerShell and Registry tools are excluded.

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
| `VISION_MODEL` | `qwen2.5vl:7b-q4_K_M` | Desktop agent |
| `CHAT_MODEL` | _(empty)_ | Chat/tools model (falls back to vision) |
| `EMBED_MODEL` | `nomic-embed-text` | Vector memory |
| `FRIDAY_PORT` | `8787` | Control Center |
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
