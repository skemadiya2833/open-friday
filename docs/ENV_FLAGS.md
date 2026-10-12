# Environment variables reference

Neutral reference for Friday configuration. Values shown are **typical defaults** when unset unless noted. See `.env.example` for a starter file.

## Server and auth

| Variable | Default | Purpose |
|----------|---------|---------|
| FRIDAY_HOST | `127.0.0.1` | Bind address |
| FRIDAY_PORT | `8787` | HTTP Control Center |
| FRIDAY_TLS_PORT | `8788` | HTTPS for phone mic (see PHONE_SETUP) |
| FRIDAY_AUTH | `local` | `off` \| `local` \| `remote` |
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
| MODEL / LOCAL_MODEL | `qwen3.5:9b` | Primary vision/decision model |
| VISION_MODEL | MODEL | Vision model override |
| CHAT_MODEL | (empty) | Chat model; empty → vision |
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
| FRIDAY_MODEL_FAST | `qwen3.5:4b` | Role: fast |
| FRIDAY_MODEL_MAIN | `qwen3.5:9b` | Role: main |
| FRIDAY_MODEL_VISION | `qwen3.5:9b` | Role: vision |
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
| AGENT_BACKEND | `legacy` | `legacy` \| `hybrid` (MCP desktop) |
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
| SKILL_EMBED_ROUTE | `false` | Embedding-based skill routing |
| CHAT_RAG_ENABLED | `false` | RAG on every chat turn |
| INDEX_CHAT_TURNS | `false` | Index chat into Chroma |

## Paths and data

| Variable | Default | Purpose |
|----------|---------|---------|
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
