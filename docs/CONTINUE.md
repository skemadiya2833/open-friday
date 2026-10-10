# Continue here (optimization + product state)

**Date:** 2026-10-10  
**Branch:** `upgrade/research-first` (do not merge / push / force unless the owner asks)  
**Tags:** `stage-N` … `stage-R` (see `git tag -l "stage-*"`)  
**Machine:** Windows 11 build 26300, Python 3.14.6 (`friday_env`), RTX 5060 Ti **16 GB**, Ollama **0.30.10**, default **`qwen3.5:9b`**

This file is the short resume. Full history: [`PROGRESS.md`](PROGRESS.md). Decisions: [`DECISIONS_NEEDED.md`](DECISIONS_NEEDED.md). Stage N–R wrap-up: [`FINAL_REPORT_2.md`](FINAL_REPORT_2.md). Earlier A–E: [`FINAL_REPORT.md`](FINAL_REPORT.md).

---

## 1. Where we are (one paragraph)

Stages **N–R** landed on this branch: CI removed + local secrets check; **passkey device auth** (loopback until a public hostname); model-role measurements (defaults unchanged); persona / humor / deep mode / plan-before-act; docs synced. Phone access stays **off the LAN** until the owner completes [`PHONE_SETUP.md`](PHONE_SETUP.md). Do **not** pull new Ollama models.

---

## 2. Optimization profile (current)

### Installed models (use only these)

`qwen3.5:9b` (default), `qwen3.5:4b`, `qwen3-vl:8b-instruct`, `qwen2.5vl:7b-q4_K_M`, `nomic-embed-text`, `qwen3-coder:30b`.

### Model & VRAM

| Knob | Current | Why |
|------|---------|-----|
| `MODEL` / `VISION_MODEL` / `CHAT_MODEL` | `qwen3.5:9b` | Unified resident model |
| `FRIDAY_MODEL_ROLES` | `false` | Opt-in after [`research/MODEL_ROLES.md`](research/MODEL_ROLES.md) |
| `MODEL_THINK` | `false` | Deep mode is opt-in (`FRIDAY_DEEP` / phrase) |
| `CHAT_NUM_PREDICT` / `CHAT_NUM_CTX` | `256` / `4096` | Short chat |
| Peak (4b+9b) | ~11 GB | Co-resident OK |
| Peak (9b+3-vl) | ~16 GB | Full card |

### Auth / phone

| Item | State |
|------|--------|
| `FRIDAY_AUTH` | **`local`** → loopback + localhost passkey |
| Remote phone | Needs registrable hostname + trusted cert → `remote` (see PHONE_SETUP) |
| Pair approve | Physical-input gate (agent cannot click Allow) |
| `SHELL_TOOLS_ENABLED` | **false** default; startup warns if .env enables |

### Persona

| Item | State |
|------|--------|
| Bible | [`PERSONA.md`](PERSONA.md) |
| Humor | `FRIDAY_HUMOR=dry` (Settings can override per browser) |
| Eval | [`research/persona_eval.json`](research/persona_eval.json) — off vs dry |

### Agent

Loop breaker, stall recovery, tools-first, multi-step plan preamble, structured tool JSON schema. `AGENT_BACKEND=legacy` default.

---

## 3. What is still open / owner must do

1. **DNS + certificate** for Option A (`friday.devoids.in` DNS-01) or Tailscale (Option B) — then `FRIDAY_AUTH=remote` + `FRIDAY_PUBLIC_HOST`.
2. **First device pairing** on the PC (matching code + physical approve) after hostname works.
3. **Voice samples** — [`VOICE_SAMPLES.md`](VOICE_SAMPLES.md) (STT still provisional).
4. Optional: enable Ollama flash-attn / q8 KV on the **service** (persistent; not done here).
5. Playwright virtual-authenticator suite — **UNVERIFIED** (playwright not installed this run).
6. Do not resume Stage H/I/J live benches unless asked.

---

## 4. How to resume

1. Read this file + `FINAL_REPORT_2.md`.
2. `git log --oneline -15` on `upgrade/research-first`.
3. `friday_env\Scripts\python.exe -m pytest -q` (auth tests need `FRIDAY_AUTH=off` via conftest).
4. Do **not** merge, push, or pull models without explicit owner ask.
5. E-stop: **Ctrl+Alt+F12**.

---

## 5. Quick health check

```powershell
friday_env\Scripts\activate
python scripts/pre_push_secrets_check.py
python -m pytest -q
python main.py --server
# Local only until PHONE_SETUP:  http://127.0.0.1:8787/
# Health: http://127.0.0.1:8787/health
```
