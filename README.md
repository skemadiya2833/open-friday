# Open Friday

A **real** local-first personal AI assistant for Windows by **Sunil Kemadiya** ([Devoids](https://devoids.in)) — not a movie prop. Modular **skills**, selective memory, voice, scheduling, calendar, **presence** callsigns, and a **desktop agent** that plans, acts, and verifies on your PC.

Talk in the Control Center; Friday routes (often **deterministically**) to chat, observe, camera, research, memory, files, tasks, CAD, presence, or **computer use**. Everyday knobs live in **Systems**. Tone may nod at classic on-screen aides; the charter is capability — see [`docs/PERSONA.md`](docs/PERSONA.md) and [`docs/PRESENCE.md`](docs/PRESENCE.md).

**Project rules & architecture handoff:** [`CONTEXT.md`](CONTEXT.md)

<p align="center">
  <img src="docs/assets/hud_desktop.png" alt="Friday Control Center desktop HUD" width="720" />
</p>

---

## Features

| Surface | What it does |
|---------|----------------|
| **Control Center** | Web UI at `http://127.0.0.1:8787` — Comms, Memory, Skills, Tasks, Reports, Tools, Devices, Systems |
| **Skills** | chat, observe (screen), camera, computer_use, research, memory, files, tasks, cad, presence |
| **Fastpath intent** | Clear screen/camera/memory/tasks asks skip chat theater (`friday/assistant/intent.py`) |
| **Presence** | Callsign skins (Friday / Jarvis / Ultron / …), model switch, optional camera presence + avatar |
| **Memory** | Chroma + local embeddings — searchable from the UI |
| **Owner profile** | Systems → About you — durable context + upgrade notes |
| **Calendar & rhythm** | iCal agenda, morning briefing, focus nudges (local data) |
| **Voice** | Push-to-talk STT; Edge / Kokoro TTS |
| **Desktop agent** | Legacy vision loop or hybrid UIA+vision via Windows-MCP |
| **Safety** | Policy tiers, approvals, hash-chained audit log, emergency stop |

Mobile-friendly layout:

<p align="center">
  <img src="docs/assets/hud_mobile.png" alt="Friday Control Center mobile layout" width="360" />
</p>

---

## Requirements

- **Windows 11**
- **Python 3.14** (tested on 3.14.6)
- **[Ollama](https://ollama.com)** for local models (0.40+ for Saluki + mmproj)
- **GPU:** NVIDIA recommended; **16 GB VRAM** target — keep **one** multimodal tag for chat + vision
- Optional: **`uv`** on PATH for Windows-MCP

### Recommended Ollama models

Install yourself (Friday does not pull unless installer `-PullModels` / `-PullVision`):

| Tag | Typical use |
|-----|-------------|
| `saluki:latest` | Unified chat + vision (GGUF + mmproj — see [`models/README.md`](models/README.md)) |
| `gemma4:12b` | Strong alternate single multimodal resident |
| `qwen3.5:9b` / `qwen3-vl:8b-instruct` | Smaller / split setups (prefer one tag on 16 GB) |
| `nomic-embed-text` | Memory embeddings |
| `qwen3-coder:30b` | Optional coding (unloads after use) |

**Context:** Friday pins a stable resident `num_ctx` for the hot chat/vision tag (shared default **8192** via `resolve_resident_num_ctx` / Saluki Modelfile) so Ollama does not reload when intent/chat/observe would otherwise flip sizes. Override with `FRIDAY_RESIDENT_NUM_CTX`.

Benchmark notes: [`docs/benchmarks.md`](docs/benchmarks.md).

---

## Install and first run

### One-click (Windows 11)

```powershell
irm https://raw.githubusercontent.com/skemadiya2833/open-friday/main/deploy/windows/install.ps1 | iex
friday doctor
friday
```

Installs under `%LOCALAPPDATA%\OpenFriday`, adds a `friday` shim to user PATH, and **does not** pull Ollama models unless you pass `-PullModels` / `-PullVision` (see [`deploy/windows/README.md`](deploy/windows/README.md)).

### Manual (developers)

```powershell
python -m venv friday_env
friday_env\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements/core.lock.txt
pip install -e .
copy .env.example .env

friday                  # tray + Control Center (same as python main.py)
friday --help           # also: friday doctor | friday version | friday serve --server
python main.py --server # HTTP only — http://127.0.0.1:8787/
```

CLI:

| Command | What it does |
|---------|----------------|
| `friday` / `friday serve` | Control Center + tray |
| `friday serve --server` | HTTP only |
| `friday doctor` | Preflight checks + next steps (never downloads models) |
| `friday doctor --json` | Machine-readable report |
| `friday version` | Print version |

Optional extras:

| Need | Install |
|------|---------|
| Voice | `pip install -r requirements/voice.lock.txt` |
| Camera (webcam) | `pip install -r requirements/camera.lock.txt` then enable + Arm in Systems |
| Dev / tests | `pip install -r requirements/dev.lock.txt` then `pytest` |
| Windows-MCP tools | Enable `windows` in `config/mcp_servers.yaml`; requires `uv` |
| Saluki + vision | `.\scripts\install_saluki.ps1` then set **both** chat & vision to `saluki` in Systems |

Regenerate locks after editing `requirements/*.in`:

```powershell
uv pip compile requirements/core.in --python-version 3.14 --python-platform windows -o requirements/core.lock.txt
```

---

## Security summary

- **Passkey auth** (`FRIDAY_AUTH=local`): loopback-only until a registrable hostname and trusted TLS cert are configured for phone access — see [`docs/PHONE_SETUP.md`](docs/PHONE_SETUP.md).
- **Request guard:** strict Host/Origin allow list; no wildcard CORS.
- **Tools:** `config/policy.yaml` — safe / confirm / deny tiers; shell off by default.
- **MCP:** disabled by default; pinned versions; dangerous tools excluded in config.
- **Before you push a fork:** `python scripts/pre_push_secrets_check.py` and `python scripts/pre_push_guard.py`.

Full detail: [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md), [`SECURITY.md`](SECURITY.md).

Emergency stop: **Ctrl+Alt+F12** cancels agent runs and revokes approvals.

---

## Architecture and docs

- [`CONTEXT.md`](CONTEXT.md) — project rules, map, fastpath, models residency
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — components and data flow
- [`docs/PRESENCE.md`](docs/PRESENCE.md) — skins, model switch, camera presence, avatar
- [`docs/design/`](docs/design/) — feature design notes
- [`docs/PERSONA.md`](docs/PERSONA.md) — assistant tone and humor
- [`docs/ENV_FLAGS.md`](docs/ENV_FLAGS.md) — configuration reference
- [`models/README.md`](models/README.md) — Ollama tags + Saluki Modelfile

Optional Vite React shell (`web/src`): set `FRIDAY_ALLOWED_ORIGINS` for `http://localhost:5173` when using `npm run dev`.

Legacy entry points: `python main.py --gui` · `python main.py --cli "Open Notepad"`

---

## Roadmap

- Stronger phone / remote access ergonomics with documented TLS setup
- Optional SearXNG-backed research provider (design in `docs/design/searxng_provider.md`)
- Continued hybrid-agent hardening and benchmark coverage
- Community skill import with quarantine and hash-bound approval (see threat model)
- Avatar lipsync engines (MuseTalk / Wav2Lip) beyond still portraits
- Releases: [`docs/RELEASE_CHECKLIST.md`](docs/RELEASE_CHECKLIST.md)

---

## Credits and license

Third-party projects and adapted code are listed in [`docs/REFERENCES.md`](docs/REFERENCES.md) and [`docs/THIRD_PARTY_NOTICES.md`](docs/THIRD_PARTY_NOTICES.md).

**License:** [MIT](LICENSE)

Maintainer: **Sunil Kemadiya** — [Devoids](https://devoids.in) · [skemadiya@gmail.com](mailto:skemadiya@gmail.com)

Contributions welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).
