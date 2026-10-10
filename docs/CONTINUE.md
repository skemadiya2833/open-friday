# Continue here (optimization + product state)

**Date:** 2026-10-10  
**Branch:** `upgrade/research-first` (do not merge / push / force unless the owner asks)  
**HEAD at last write:** see `git log -1 --oneline`  
**Machine:** Windows 11, Python 3.14.6 (`friday_env`), RTX 5060 Ti **16 GB**, Ollama, default model **`qwen3.5:9b`**

This file is the short resume. Full history: [`PROGRESS.md`](PROGRESS.md). Decisions: [`DECISIONS_NEEDED.md`](DECISIONS_NEEDED.md). Stage A–E wrap-up: [`FINAL_REPORT.md`](FINAL_REPORT.md).

---

## 1. Where we are (one paragraph)

Friday is past the research-first stages (A–E, G, K, L/M partial). Recent work (2026-10-07 → 10) was **product polish and latency**: stop planner TYPE loops, faster chat/planner (thinking off, short predicts), realtime voice + barge-in, agentic reminders, Memory forget, **LAN phone access** (bind `0.0.0.0`, firewall, HTTPS for mic), mobile HUD layout, and **research that fetches results once** instead of opening Google tabs forever. Desktop agent quality on multi-step tasks is still weak; **do not switch the default model to Qwen3.8-27B** on this 16 GB card without a fit-in-VRAM quant.

---

## 2. Optimization profile (current)

### Model & VRAM (active)

| Knob | Current | Why |
|------|---------|-----|
| `MODEL` / `VISION_MODEL` / `CHAT_MODEL` | `qwen3.5:9b` (unified) | One resident model → no load/unload thrash on 16 GB |
| `MODEL_THINK` | `false` | Thinking burned planner ticks; JSON decisions only |
| `CHAT_NUM_PREDICT` | `256` | Short chat replies |
| `CHAT_NUM_CTX` | `4096` | Cap KV for chat |
| `MODEL_NUM_PREDICT` | `1024` (planner often ≤512) | Cap runaway generations |
| `SKILL_EMBED_ROUTE` | `false` | Keyword router; embeddings are slower |
| `CHAT_RAG_ENABLED` / `INDEX_CHAT_TURNS` | `false` | No embed call every turn |
| `STREAM_USE_VIDEO` / `STREAM_FRAME_COUNT` | `false` / `1` | Lighter observe path |
| Peak VRAM (9b hybrid subset) | ~8.5–12.3 GB | Room for Whisper if STT stays modest |

### Agent speed / reliability (code)

| Item | State |
|------|--------|
| Loop breaker (state cycles) | ON — stop after repeated revisits |
| Stall detector + recovery ladder | ON (`friday/agent/stall.py`) |
| Empty TYPE rejection + text recovery | ON — planner must not re-observe forever with empty text |
| Tools-first router | ON in product (`FRIDAY_TOOLS_FIRST=false` disables); OFF in benches |
| Composite multi-line TYPE | ON |
| Macros / planner-executor extras | OFF by default (D-023 / D-026) |
| Experience memory | OFF (`FRIDAY_MEMORY=off`, D-021) |
| `AGENT_BACKEND` | Still **`legacy`** default; hybrid opt-in |

### Voice

| Item | State |
|------|--------|
| Default pacing | **Realtime** (override in overlay / Settings) |
| Barge-in | Mic stays live while speaking; stop words / long non-echo interrupt |
| Browser TTS in realtime | Preferred when possible (skip slow server TTS path) |
| STT accuracy on owner voice | **UNVERIFIED** — run `docs/VOICE_SAMPLES.md` |
| Phone mic | Needs **HTTPS** (`https://<lan-ip>:8788/` after restart); HTTP LAN is not a secure context |

### Research skill

| Item | State |
|------|--------|
| `web_search` | Fetches DuckDuckGo HTML / Google News RSS; returns titles+snippets |
| Duplicate same query | Cached ~10 min; ReAct refuses identical tool call twice |
| Tab spam | Fixed — no default `webbrowser.open` on every search |

### Phone / Control Center

| Item | State |
|------|--------|
| Bind | `FRIDAY_HOST=0.0.0.0` (listen-all); browser URL is `127.0.0.1`, not `0.0.0.0` |
| Firewall | Inbound TCP **8787** + **8788** (Private) added when elevated |
| HTTPS | Self-signed LAN cert in `data/tls/`; daemon uvicorn on `FRIDAY_TLS_PORT` (default 8788) |
| Ctrl+C | Win32 console handler + tray quit (`friday/shutdown.py`) |
| Mobile layout | Bottom nav, stacked composer, HTTPS banner (`styles.css?v=6`, `app.js?v=9`) |

---

## 3. Model advice (do not ignore)

**Stay on `qwen3.5:9b` for Friday day-to-day.**

| Option | On 5060 Ti 16 GB | Expect |
|--------|------------------|--------|
| Stock `qwen3.8:27b` Q4_K_M | ~18 GB weights → **CPU offload** | ~8 tok/s class (spill); smarter, sluggish agent |
| Custom ~15 GB Q4 / Q3_K_M | Can fit with short ctx | ~20–26 tok/s class if fully on GPU |
| Q8_0 27B | Too big | Few tok/s |

Constraint still in force: **no new Ollama downloads** unless the owner explicitly asks. If they ask later: pull only a fit-in-VRAM quant, keep `num_ctx` 4k–8k, unload Whisper first.

---

## 4. What is still open / next (priority order)

1. **Restart Friday** so HTTPS + research + HUD cache bumps are live; verify phone `https://192.168.1.24:8788/` (Advanced → Proceed → Allow mic).
2. **Ask “what’s the news”** once — confirm one search + spoken/text briefing, no tab storm.
3. Optional live: tools-first Notepad save path; TYPE into Notepad without empty-text loop (desktop scratch only).
4. Owner voice STT: `docs/VOICE_SAMPLES.md` + `scripts/bench_stt_real.py` → decide `VOICE_STT_MODEL` in `.env`.
5. H3 VRAM: `scripts/vram_coload.py` with 9b + Whisper (never run to completion for this stack).
6. Hybrid: keep off as default until multi-step pass rate improves; live Chrome/canvas failures still unexplained.
7. Stage H/I/J benches: **stopped by owner** — do not resume live desktop benches unless asked.
8. CI on GitHub: workflow exists, **never run**.
9. `friday_env` may still need `uv pip install -r requirements/core.lock.txt` for `google-genai` (cloud fallback).

---

## 5. How to resume after a context reset

1. Read this file, then skim `docs/PROGRESS.md` from “2026-10-07” downward.
2. `git log --oneline -20` on `upgrade/research-first`.
3. Check `.env` still has unified 9b + `MODEL_THINK=false` + LAN host if phone is needed.
4. Do **not** merge to main, push, force, or pull new models without explicit owner ask.
5. Prefer unit tests over live desktop; e-stop is **Ctrl+Alt+F12**.

---

## 6. Key commits (product / optimization wave)

| Commit | Topic |
|--------|--------|
| `33b7710` | Research: fetch once, brief user, no tab spam |
| `2bd8a16` | Phone HTTPS mic + mobile HUD |
| `9dd0b56` / `0e7e6d5` / `bcfc7d3` | Firewall, browser URL, LAN bind + private Host |
| `c5c022a` | Ctrl+C stops tray process |
| `7188835` | Memory Forget / Forget all |
| `7178766` | Empty TYPE loops + thinking off planner |
| `ccdb018` | Realtime speech + barge-in |
| `0d77bbf` | Voice greeting loop, memory overview, agentic reminders |
| `9cc7690` | Loop breaker, composite type, tools-first |

---

## 7. Quick health check

```powershell
friday_env\Scripts\activate
python main.py --server
# Local:  http://127.0.0.1:8787/
# Phone:  http://192.168.1.24:8787/          (typing)
# Mic:    https://192.168.1.24:8788/         (self-signed)
# Health: http://127.0.0.1:8787/health
```
