# Environment variables reference

Neutral reference for Friday configuration. Values shown are **typical defaults** when unset unless noted. See `.env.example` for a starter file.

## Prefer Systems → Preferences

Everyday knobs (persona, **chat/vision Ollama tags**, agent backend, tools-first, memory, approvals, shell tools, TTS voice, model roles, low-end) are owned by **Systems → Preferences** (`data/runtime_prefs.json`). Resolution: **UI → env → optima**. Host/bind/auth/API keys/paths stay env-only (need restart). Use **Reset to optima** in Systems for recommended defaults. Switch models from the web UI — no `.env` edit required.

## Server and auth

| Variable | Default | Purpose |
|----------|---------|---------|
| FRIDAY_HOST | `127.0.0.1` | Bind address |
| FRIDAY_PORT | `8787` | HTTP Control Center |
| FRIDAY_TLS_PORT | `8788` | HTTPS for phone mic (see PHONE_SETUP) |
| FRIDAY_AUTH | `local` | `off` \| `local` \| `lan` (phone Wi‑Fi, approve + optional passkey) \| `remote` |
| FRIDAY_PUBLIC_HOST | (empty) | Registrable domain for WebAuthn when `remote` |
| FRIDAY_ORIGIN | derived | Browser origin for passkeys |
| FRIDAY_API_TOKEN | (empty) | Optional bearer for scripts |
| FRIDAY_ALLOWED_ORIGINS | (empty) | Extra CORS origins (e.g. Vite dev) |
| FRIDAY_ALLOWED_HOSTS | (empty) | Extra Host header names |
| FRIDAY_SESSION_TTL | `86400` | Passkey session lifetime (seconds) |
| FRIDAY_SESSION_COOKIE | `friday_session` | Cookie name |
| FRIDAY_RP_NAME | `Friday` | WebAuthn RP display name |

## Models (Ollama)

| Variable | Default | Purpose |
|----------|---------|---------|
| OLLAMA_HOST | `http://localhost:11434` | Ollama base URL |
| MODEL / LOCAL_MODEL | `gemma4:12b` | Primary model tag (Systems chat/vision prefs override) |
| CHAT_MODEL | gemma4:12b | Chat model (Systems → Preferences overrides) |
| VISION_MODEL | gemma4:12b | Vision / screen look (Systems overrides; must be multimodal) |
| EMBED_MODEL | `nomic-embed-text` | Embeddings for memory |
| MODEL_KEEP_ALIVE | `-1` | Ollama keep-alive |
| MODEL_NUM_PREDICT | `1024` / low-end `768` | Max tokens per decision |
| MODEL_NUM_CTX | `8192` | Context window |
| MODEL_TEMPERATURE | `0.2` | Sampling temperature |
| MODEL_TOP_P | `0.9` | Top-p |
| MODEL_THINK | `false` | Native thinking mode |
| MODEL_COORD_SPACE | `pixel` | `pixel` \| `grid1000` \| `auto` |
| CHAT_NUM_PREDICT | `256` | Chat reply cap |
| CHAT_NUM_CTX | `4096` | Chat context |
| FRIDAY_MODEL_ROLES | `false` | Enable fast/main/vision/coder map |
| FRIDAY_MODEL_FAST | same as MAIN | Role: fast (defaults to 9b; set 4b only if splitting) |
| FRIDAY_MODEL_MAIN | `gemma4:12b` | Role: main (same multimodal as vision on 16GB; see `models/README.md`) |
| FRIDAY_MODEL_VISION | `gemma4:12b` | Screen/camera — must be a vision-capable tag |
| FRIDAY_VISION_KEEP_ALIVE | `-1` / `3m` | Keep VL loaded; use `3m` only if swapping with a separate MAIN |
| FRIDAY_MODEL_CODER | `qwen3-coder:30b` | Role: coder (heavy) |
| FRIDAY_COMPLEXITY_ROUTING | `false` | Heuristic 4b/9b routing |
| FRIDAY_AUTOSTART_OLLAMA | `true` | Start Ollama if missing |
| FRIDAY_MAIN_KEEP_ALIVE | MODEL_KEEP_ALIVE | Role-specific keep-alive |
| FRIDAY_CODER_KEEP_ALIVE | `0` | Unload coder after use |
| FRIDAY_EMBED_KEEP_ALIVE | `10m` | Embed model keep-alive |
| FRIDAY_GPU_IDLE_UTIL_PCT | `15` | GPU util threshold for background work |

## Agent loop and safety

| Variable | Default | Purpose |
|----------|---------|---------|
| AGENT_BACKEND | *(auto)* | `legacy` \| `hybrid`. Empty = **auto**: hybrid when Windows-MCP is enabled in `config/mcp_servers.yaml`, else legacy screenshot loop |
| MAX_ITERATIONS | `60` | Desktop loop cap |
| MAX_EMPTY_DECISIONS | `4` | Empty parser tolerance |
| MAX_TOOL_STEPS | `8` | Tool loop cap |
| MAX_STUCK_ACTIONS | `8` | Consecutive skip guard |
| FRIDAY_TOOLS_FIRST | `true` | Deterministic tools before GUI |
| FRIDAY_MEMORY | `off` | Experience memory: `off\|record\|read\|on` |
| FRIDAY_MEMORY_DEFER | off | Defer ingest (benchmarks) |
| FRIDAY_APPROVAL_TIMEOUT | `120` | Confirm-tier wait (seconds) |
| FRIDAY_APPROVAL_MODE | `attended` | `attended` \| `unattended` |
| FRIDAY_APPROVAL_BEEP | `true` | Audible approval nudge |
| FRIDAY_REQUIRE_PHYSICAL_INPUT | `false` | Physical key/mouse for approvals |
| FRIDAY_PAIR_APPROVE | `physical` | Pairing: `physical` \| `hello` \| `either` |
| FRIDAY_ESTOP | (on) | `false` disables global hotkey |
| FRIDAY_STOP_HOTKEY | `ctrl+alt+f12` | Emergency stop chord |
| FRIDAY_INPUT_MONITOR | auto | Low-level input monitor |
| FRIDAY_SECRETS_MODE | `redact` | `warn` \| `redact` \| `block` |
| FRIDAY_INJECTION_MODE | `warn` | Prompt injection handling |
| SHELL_TOOLS_ENABLED | `false` | Shell tool registration |

## Voice

| Variable | Default | Purpose |
|----------|---------|---------|
| VOICE_ENABLED | `true` | Voice features |
| VOICE_STT_MODEL | `large-v3-turbo` | Whisper model (UNVERIFIED on your voice) |
| VOICE_STT_DEVICE | `auto` | STT device |
| VOICE_STT_COMPUTE | `float16` | STT compute type |
| VOICE_TTS_VOICE | `en-US-AvaNeural` | Edge TTS voice |
| FRIDAY_VAD_MODEL | (optional) | VAD model path |
| WAKE_WORD_MODEL | `hey_jarvis` | openWakeWord model |
| WAKE_WORD_THRESHOLD | `0.5` | Wake sensitivity |
| FRIDAY_TTS_PYTHON | (optional) | Python for alternate TTS worker |
| FRIDAY_TTS_MODELS | `data/voice_lab/models` | Local TTS model dir |

## Persona and UX

| Variable | Default | Purpose |
|----------|---------|---------|
| FRIDAY_OWNER_NAME | `boss` | Address name |
| FRIDAY_HUMOR | `dry` | `off` \| `dry` \| `full` \| `roast` |
| FRIDAY_DEEP | `false` | Bounded thinking mode |
| FRIDAY_DEEP_TOKEN_BUDGET | `512` | Think token cap |
| FRIDAY_DEEP_TIMEOUT | `45` | Think timeout (seconds) |
| FRIDAY_TOASTS | `on` | Windows toast notifications |
| FRIDAY_MORNING_BRIEFING | off | Built-in morning job |
| FRIDAY_EOD_SHUTDOWN | off | End-of-day briefing job |
| FRIDAY_WEEKLY_REVIEW | off | Weekly review job |

## Skills and experimental

| Variable | Default | Purpose |
|----------|---------|---------|
| FRIDAY_SKILLS_DIR | builtin skills path | manifest.yaml skills |
| SKILL_PROPOSALS | `false` | Agent-drafted SKILL.md proposals |
| FRIDAY_SENSORS | `false` | Read-only sensor tool |
| FRIDAY_CAMERA | `off` | Opt-in desk webcam (`on`/`true` to enable) |
| FRIDAY_CAMERA_INDEX | `0` | Default OpenCV device index (Systems UI pick overrides via `data/camera_prefs.json`) |
| FRIDAY_CAMERA_ARM_TTL | `300` | Arm grant TTL in seconds (30–3600) |
| FRIDAY_CAD | `off` | Fallback only — prefer Systems → CAD (`cad_enabled`) |
| FREECAD_INSTALL | `C:\Program Files\FreeCAD 1.1` | Fallback FreeCAD root; Systems pref `freecad_install` wins |
| FREECAD_S1_REPO | _(empty)_ | Fallback biome-s1 path; default vendor under `data/vendor/biome-s1` |
| FREECAD_S1_MODEL | `shhivv/taiga-s1` | Hugging Face id or local weights dir |
| FREECAD_S1_PORT | `8765` | FreeCAD GUI server socket |
| FREECAD_S1_PYTHON | _(empty)_ | Fallback worker Python with torch + freecad_s1 |
| SKILL_EMBED_ROUTE | `false` | Embedding-based skill routing |
| CHAT_RAG_ENABLED | `false` | RAG on every chat turn |
| INDEX_CHAT_TURNS | `false` | **Deprecated / leave off.** Chat turns are not memory (SQLite holds plan/facts/calendar; Chroma is for short semantic notes only). |

## Paths and data

| Variable | Default | Purpose |
|----------|---------|---------|
| FRIDAY_UI | `public` | Control Center: `public` (`web/public`, default) or `dist` (Vite). Stale `web/dist` no longer shadows live UI unless opted in |
| FRIDAY_DATA_DIR | `./data` | State root |
| FRIDAY_WORKSPACE | `data/workspace` | Agent workspace |
| FRIDAY_CONFIG_DIR | `./config` | Policy and MCP yaml |
| FRIDAY_POLICY_FILE | `config/policy.yaml` | Tool policy |
| FRIDAY_MCP_CONFIG | `config/mcp_servers.yaml` | MCP servers |
| FRIDAY_AUDIT_LOG | `data/audit/tool_calls.jsonl` | Audit chain |
| FRIDAY_PRIVATE_LIBRARY | default under data | Local doc library |

## Cloud fallback

| Variable | Default | Purpose |
|----------|---------|---------|
| CLOUD_PROVIDER | `gemini` | `gemini` \| `openai` \| `none` |
| GEMINI_API_KEY | (empty) | Gemini API key |
| OPENAI_API_KEY | (empty) | OpenAI API key |
| GEMINI_MODEL | auto-pick | Override Gemini model id |

## Performance profile

| Variable | Default | Purpose |
|----------|---------|---------|
| LOW_END_MODE | `false` | Smaller frames, lighter verify (or `--low-end`) |
| LIVE_MODE | `true` | Live vision feed |
| OVERLAY_ENABLED | `true` | On-screen overlay |
| AIM_VERIFY_ENABLED | true / low-end false | Click verification |
| FRIDAY_ALLOW_MULTI | off | Allow second Friday instance (tests) |

## Ollama service tuning (external)

Set on the **Ollama service**, not Friday:

| Variable | Purpose |
|----------|---------|
| OLLAMA_FLASH_ATTENTION | Flash attention (D-036 owner opt-in) |
| OLLAMA_KV_CACHE_TYPE | KV cache quantization |

## Diagnostics

| Command / route | Purpose |
|-----------------|--------|
| `python main.py --doctor` | GPU, Ollama, models, ports — **never downloads** |
| `/api/ops/summary` | Aggregated local ops counts |
| `/api/health/detail` | Full health JSON |
