# Open Friday — project context

Read this before changing code. Source of truth for humans and agents working on **Open Friday**.

Install, doctor, and day-to-day CLI live in [`README.md`](README.md). Deep design notes: [`docs/`](docs/). Env catalog: [`docs/ENV_FLAGS.md`](docs/ENV_FLAGS.md). Models: [`models/README.md`](models/README.md).

---

## What this is

A **real local-first personal AI assistant for Windows** by **Sunil Kemadiya** ([Devoids](https://devoids.in)) — not a movie prop.

- Control Center HUD at `http://127.0.0.1:8787/`
- Skills: chat, observe (screen), camera, computer_use, research, memory, files, tasks, cad, presence
- Desktop agent (legacy vision loop or hybrid UIA + vision via Windows-MCP)
- Selective memory (Chroma), calendar/rhythm, voice, policy + approvals + e-stop

**Callsign / presence:** cinematic F.R.I.D.A.Y. tone and skins (Jarvis, Ultron, …) — **inspired only**. Never copy film dialogue or claim franchise characters. Style ≠ capability: skins change voice/HUD/humor, never tools, approvals, or safety.

Default spoken address: **boss** (per-machine prefs). Maintainer in Cursor chats: **Sunil**.

---

## Non-negotiables

1. **Capability over spectacle** — tools, desktop agent, reflexes, diary, blackout beat empty narration.
2. **Truth over theater** — invent nothing (tool runs, files, CAD, search). If evidence is missing, say so in one line.
3. **Prompt-first, not dump-guard stacking** — lean system prompts; reply guards catch leaks, they are not the product.
4. **Deterministic tool fastpath** — clear screen/camera/memory/tasks/voice-pick/model-talk asks must not burn chat/research tokens deciding to act (`friday/assistant/intent.py`).
5. **One multimodal resident on 16 GB** — same Ollama tag for chat + vision when possible. Never pair a text-only GGUF with a separate VL.
6. **Stable `num_ctx`** — changing context size reloads Ollama. Friday pins `resolve_resident_num_ctx()` (shared chat+vision defaults to **8192**; override `FRIDAY_RESIDENT_NUM_CTX`).
7. **Terminal-first** — PowerShell / shell for files, git, installs, processes. Desktop vision only for real GUI work.
8. **Safety stays** — policy tiers, approvals, hash-chained audit, e-stop (`Ctrl+Alt+F12`), blackout. Shell off by default.

---

## Stack

| Layer | Choice |
|-------|--------|
| Runtime | Python **3.14**, Windows 11 |
| Server | FastAPI + Uvicorn (`friday/server`) — HTTP `8787`, TLS `8788` |
| UI | Vanilla Control Center `web/public` (optional Vite shell) |
| Models | **Ollama** (local); optional cloud fallback |
| Memory | Chroma + `nomic-embed-text` |
| Voice | Whisper STT + Edge / Kokoro TTS (optional extras) |
| Agent | Legacy screenshot loop or **hybrid** Windows-MCP |
| CAD | FreeCAD + Taiga-S1 (opt-in Systems) |
| Package | `open-friday` **3.0.0** — CLI entry `friday` |

---

## Models (current practice)

| Role | Typical tag | Notes |
|------|-------------|--------|
| Chat + vision (single resident) | `saluki:latest` or `gemma4:12b` | Set **both** Systems chat & vision to the same multimodal tag |
| Embeddings | `nomic-embed-text` | Memory |
| Optional coder | `qwen3-coder:30b` | Unloads after use (`FRIDAY_CODER_KEEP_ALIVE=0`) |

**Saluki:** Underdog 27B IQ2 + mmproj → Ollama tag via `models/saluki/Modelfile` / `scripts/install_saluki.ps1`. Modelfile defaults: `num_ctx 8192`, `temperature 0.6`, `top_p 0.95`, `top_k 20`. Must include mmproj for screen/camera.

**Residency:** `friday/models/manager.py` + `resolve_resident_num_ctx()` — do not thrash keep-alive or per-call `num_ctx` on the hot tag.

Everyday model picks: **Systems → Preferences** (`data/runtime_prefs.json`), not `.env`.

---

## Repo map

```
main.py / friday/cli.py     # Entry: tray + Control Center, doctor, version
friday/
  server/                   # FastAPI routes, auth, SSE/WS
  assistant/                # Intent, reflexes, reply_guard, sessions
  skills/builtin/           # chat, observe, camera, computer_use, …
  agent/                    # Desktop loop (legacy + hybrid)
  models/                   # Ollama client, ModelManager, roles
  presence/ + avatar/       # Skins, model switch, camera presence, lipsync facade
  prompts.py                # All model-facing prompt text
  tasks/                    # Day plan, scheduler hooks
  voice/ camera/ cad/ …
web/public/                 # Control Center HUD
models/                     # Local Modelfiles (e.g. saluki)
config/                     # policy.yaml, mcp_servers.yaml
docs/                       # Architecture, persona, threat model, design/
deploy/windows/             # One-click installer
tests/                      # pytest
data/                       # Runtime (gitignored): prefs, memory, audit, TLS
```

---

## Intent → skill (fastpath)

Clear asks skip LLM classify when possible:

| Ask | Skill |
|-----|--------|
| See / look at my screen, wallpaper, screenshot | `observe` |
| See me / webcam / desk camera | `camera` |
| Remember / what do you know | `memory` |
| Agenda / schedule list vs plan-my-day | `tasks` (`is_schedule_list_request` vs meta plan) |
| Switch callsign / model | `presence` |
| Act on the desktop | `computer_use` |

Pushback after a missed look re-triggers observe/camera — never a chat essay about tools being “unwired.”

Optics / prompt dumps are rejected in `friday/assistant/reply_guard.py` and `friday/models/local.py` (`_looks_like_optics_dump`).

---

## Presence

Skins: friday · jarvis · ultron · vision · karen · edith — see [`docs/PRESENCE.md`](docs/PRESENCE.md).

- Pref `presence_skin`; voice lines switch TTS + HUD theme
- Camera presence (opt-in glance per turn)
- Avatar still / MuseTalk / Wav2Lip under `friday/avatar/`

---

## Security posture (summary)

Loopback-first; Host/Origin guard; passkey modes (`local` / `lan` / `remote`); tiered tools in `config/policy.yaml`; audit chain; SSRF block on research. Details: [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md), [`SECURITY.md`](SECURITY.md).

---

## Where to change what

| Goal | Start here |
|------|------------|
| Routing / fastpath | `friday/assistant/intent.py` |
| Spoken charter / tool prompts | `friday/prompts.py` |
| Dump / optics guards | `friday/assistant/reply_guard.py`, `friday/models/local.py` |
| Model load / ctx residency | `friday/models/manager.py`, `friday/config.py` (`resolve_resident_num_ctx`) |
| Screen look | `friday/skills/builtin/observe/` |
| Day plan vs schedule list | `friday/tasks/day_plan.py` |
| Presence skins | `friday/presence/` |
| HUD | `web/public/` |

---

## Related docs

| Doc | Role |
|-----|------|
| [`README.md`](README.md) | Install, doctor, features table |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Component diagram |
| [`docs/PERSONA.md`](docs/PERSONA.md) | Tone charter |
| [`docs/PRESENCE.md`](docs/PRESENCE.md) | Skins / avatar |
| [`docs/ENV_FLAGS.md`](docs/ENV_FLAGS.md) | Full env reference |
| [`models/README.md`](models/README.md) | Ollama tags + Saluki build |
| [`docs/PHONE_SETUP.md`](docs/PHONE_SETUP.md) | LAN / TLS phone |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Dev workflow |
