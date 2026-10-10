# Final report — Stages S–U (2026-10-10)

**Branch:** `upgrade/research-first` (not merged, not pushed)  
**Tags:** `stage-S`, `stage-T`, `stage-U`  
**Rule:** nothing claimed as working unless executed; else **UNVERIFIED**.

---

## Task status matrix

| Stage / task | Status | Evidence |
|--------------|--------|----------|
| **S1** Playwright + Chromium virtual authenticator | **PASS** | `playwright==1.63.0` in `requirements/dev.*`; `tests/test_webauthn_virtual.py` **6 passed** (register, login, step-up, revoke, replayed challenge, wrong origin/RP, UV-false path, cloned counter, enrollment reuse/expiry) |
| **S2** Second-client LAN / forged header probe | **PASS** | `docs/research/lan_auth_probe.json` — **9/9** denied (401/403) including SSE + WebSocket |
| **S3** Physical-input gate vs synthetic | **PASS** (auto) | `docs/research/physical_gate_check.json` — SendInput/keybd_event refused; Windows-MCP cited from prior probe; Hello alternative documented (`FRIDAY_PAIR_APPROVE`) |
| **S3b** Owner real-key manual confirm | **UNVERIFIED** | Run `scripts/physical_gate_manual.py` without `--auto-only` |
| **S4** Config drift on `/health` | **PASS** | `config_drift` in health detail; non-loopback without remote = **error**; tests in `test_config_drift.py` |
| **T1** Deterministic humor suppression | **PASS** | `blocked_context()` before model; `tests/test_humor_suppression.py`; security-prompt leak now fails loudly |
| **T2** Thumbs up/down feedback | **PASS** (code) | `/api/feedback` + UI buttons; local bounded store; Settings-visible votes |
| **T3** Persona eval re-run | **PASS** | `persona_eval.json`: off **1.0/1.0/1.0**, dry **1.0/1.0/1.0** (was 0.97). Scoring: **scripted rubric** in `scripts/eval_persona.py` (correctness/concision/persona heuristics; **not** a human or LLM judge). Limits: no ground-truth tools execution; film-quote regex only; quip detection is paragraph heuristic |
| **U1** Tools-first expansion | **PASS** | `friday/agent/direct_tools.py` + router prefer; unit `test_direct_tools_route.py`; smoke via live bench (opens apps/folders/files) |
| **U2** JSON-schema structured outputs | **PASS** | Hybrid + vision planner use `PLANNER_SCHEMA`; `parse_schema_bench.json`: fail rate **0.8 → 0.0** on fixed set |
| **U3** Fast-brain 4b vs 9b | **PASS** | `fast_brain_bench.json`: 4b 3.08s / 0.975 correct; 9b 3.36s / 1.0. **Keep 9b default** |
| **U4** Legacy vs hybrid live (15 min) | **PASS** (tools-first) | `backend_live_stu.json`: **15/15** each via direct tools; recommend **legacy** (tie → keep default). Full GUI “Calculator and add” path **UNVERIFIED** (not required once tools-first handled opens) |
| **U5** Ollama version + release notes | **PASS** | Installed **0.30.10**; `docs/research/OLLAMA_RELEASE_NOTES.md` — no upgrade |

---

## Authentication / security (delta)

- Virtual authenticator happy path + adversarial unit cases verified under Playwright.
- Forged Host/Origin and unauthenticated API/SSE/WS rejected on a live server.
- Pair approve: physical default; `FRIDAY_PAIR_APPROVE=hello|either` for RDP lock-out.
- Config drift surfaced on `/api/health/detail`.

---

## Persona / humor

| Humor | correctness | concision | persona |
|-------|-------------|-----------|---------|
| off | 1.0 | 1.0 | 1.0 |
| dry | 1.0 | 1.0 | 1.0 |

Scoring method: fixed 20 prompts → local model reply → **Python rubric** (`score_reply`). Limits listed above.

---

## Model / backend measurements

| Item | Result |
|------|--------|
| Structured outputs | parse fail 80% → **0%** on micro-set |
| Fast 4b | slightly faster, −0.025 correctness → **no default change** |
| Live backends | 15–15 via tools-first → **keep AGENT_BACKEND=legacy** |
| Ollama | 0.30.10; MTP/flash-attn not enabled |

---

## Defaults changed this run

| Default | Change | Why |
|---------|--------|-----|
| Playwright | added to **dev** lock | S1 |
| `FRIDAY_PAIR_APPROVE` | new (`physical`) | D-039 |
| Non-loopback without remote | warn → **error** | D-040 |
| Humor security suppression | filter-only → **pre-model gate** | T1 |
| Planner/hybrid schema | format_json → **+ PLANNER_SCHEMA** | U2 |
| Agent loop log arrow | unicode → ASCII | Windows cp1252 crash |

**Unchanged:** `qwen3.5:9b` default, `AGENT_BACKEND=legacy`, no Ollama upgrade, no model downloads.

---

## Decisions (owner)

- **D-039** Pair approve physical + Hello fallback  
- **D-040** Non-loopback bind without remote auth is an error  
- Keep 9b; keep legacy backend after tied live counts  

---

## Installed / needing installation

| Item | Status |
|------|--------|
| Playwright 1.63.0 + Chromium headless shell | **Installed** (dev) |
| New Ollama models / Ollama upgrade | **None** |
| certbot / Tailscale / phone DNS | Still owner (PHONE_SETUP) |

---

## Manual steps for the owner

1. Complete DNS + cert + `FRIDAY_AUTH=remote` (PHONE_SETUP) before phone passkeys.  
2. Optional: `python scripts/physical_gate_manual.py` (press a real key).  
3. If RDP blocks physical gate: `FRIDAY_PAIR_APPROVE=hello` and step-up on PC before Approve.  
4. Voice samples still provisional (`VOICE_SAMPLES.md`).  
5. Review thumbs feedback in Control Center; clear via `DELETE /api/feedback`.  
6. Align `.env` with safe defaults if health shows `config_drift`.

---

## Hard skips

Admin elevation, money, real accounts, persistent Ollama service env, merge/push, model downloads.

---

## Git checkpoints

| Tag | Topic |
|-----|--------|
| `stage-S` | WebAuthn suite, LAN probe, physical/Hello, config drift |
| `stage-T` | Humor gate, thumbs, persona eval |
| `stage-U` | Direct tools, schema bench, fast-brain, live backends, Ollama notes |

---

## Open / UNVERIFIED

- Owner physical keypress (interactive).  
- Live phone pairing (needs hostname).  
- Hybrid vs legacy on multi-step GUI tasks that tools-first cannot handle (e.g. Calculator arithmetic via UI).  
- Windows-MCP click refusal re-measured this run (prior probe only).  
- Flash-attn / KV q8 / MTP on newer Ollama.
