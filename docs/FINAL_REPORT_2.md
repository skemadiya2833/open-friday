# Final report — Stages N–R (2026-10-10)

**Branch:** `upgrade/research-first` (not merged, not pushed)  
**Tags:** `stage-N`, `stage-O`, `stage-P`, `stage-Q`, `stage-R`  
**Rule:** nothing claimed as working unless executed; else **UNVERIFIED**.

---

## Task status matrix

| Stage / task | Status | Evidence |
|--------------|--------|----------|
| **N1** Delete `.github/workflows/ci.yml` | **PASS** | File gone; commit `13bab26` / tag `stage-N` |
| **N2** Strip CI mentions (README, CONTRIBUTING, docs) | **PASS** | CONTRIBUTING: “There is no CI”; README points to local secrets check |
| **N3** Local pre-push secrets check | **PASS** | `scripts/pre_push_secrets_check.py` + `tests/test_pre_push_secrets.py` |
| **N4** `.gitignore` for secrets / tls / audit / memory | **PASS** | `.env.*`, `*.pem`, `*.key`, credential filenames |
| **O1** `webauthn` 2.x on Python 3.14.6 | **PASS** | Installed `webauthn==2.8.0` (cryptography 50.0.2) in `friday_env` |
| **O2** Auth package + routes + Devices UI | **PASS** | `friday/auth/*`, `routes_auth.py`, `web/public/auth.js`; unit `tests/test_auth_passkeys.py` |
| **O3** Loopback until public hostname | **PASS** (code) | `FRIDAY_AUTH=local` default; remote needs `FRIDAY_PUBLIC_HOST` |
| **O4** Pairing + physical gate + enrollment token | **PASS** (unit) | Matching code; physical-input required for approve |
| **O5** WebAuthn register/login/session/roles/step-up | **PASS** (unit) | Cookie session; roles chat→admin; step-up 60 s |
| **O6** Exact Host allow-list; token fallback optional | **PASS** (unit) | RequestGuard; no RFC1918 Host relaxation |
| **O7** `docs/PHONE_SETUP.md` (DNS-01 + Tailscale) | **PASS** | Manual steps documented; software not auto-installed |
| **O8** Chromium virtual authenticator suite | **UNVERIFIED** | Playwright not installed this run |
| **O9** LAN script: unauth / forged Origin rejected | **UNVERIFIED** | Unit coverage for guard; live second-client script not run |
| **O10** Live phone pairing | **UNVERIFIED** | Needs owner DNS + trusted cert |
| **O11** `schedule_task` reminder-only SAFE | **PASS** (unit) | Non-reminder / computer_use schedule refused |
| **O12** `SHELL_TOOLS_ENABLED` default false + warn | **PASS** | Config default false; startup warn if .env enables |
| **P1** Ollama version / MTP speculative decode | **PASS** | Ollama **0.30.10** — MTP not available; not enabled |
| **P2** Structured outputs / role map | **PASS** | `format_schema`, `TOOL_CALL_SCHEMA`, `friday/models/roles.py` |
| **P3** VRAM / latency / co-residency bench | **PASS** | `docs/research/model_roles_bench.json` + `MODEL_ROLES.md` |
| **P4** Change default model | **SKIPPED** (by design) | Data keeps **`qwen3.5:9b`**; roles opt-in only |
| **P5** Flash-attn + KV q8_0 | **SKIPPED** | Would be persistent Ollama service change |
| **P6** Windows Agent Workspace / on-device MCP | **UNVERIFIED** (research) | Build **26300**; preview features not enabled / not proven present |
| **Q1** Plan-verify-summarize / tools-first | **PASS** (code+unit) | `friday/agent/behavior.py`; wired into ReAct + computer_use |
| **Q2** Deep mode | **PASS** (unit) | Opt-in; think budget + timeout fallback |
| **Q3** Persona module + `PERSONA.md` | **PASS** | Original copy; owner = boss configurable |
| **Q4** Humor policy + Settings | **PASS** | `friday/humor.py`; Settings + chat `humor` field |
| **Q5** 20-prompt eval off vs dry | **PASS** | `persona_eval.json`: off 1.0/1.0/1.0; dry 1.0/1.0/**0.97** (1 security-row quip penalty) |
| **R1** Sync README / `.env.example` / CONTINUE | **PASS** | No qwen2.5vl pull; auth/phone; installed models list |
| **R2** Local unit tests | **PASS** | **338 passed** after intent-test alignment (`docs/research/pytest_stage_r.txt`) |
| **R3** This report | **PASS** | `docs/FINAL_REPORT_2.md` |

---

## Authentication threat model (updated)

| Threat | Mitigation | Status |
|--------|------------|--------|
| Unauthenticated LAN desktop control | Default **loopback**; remote off until hostname | Code PASS; live phone UNVERIFIED |
| Passkey against IP / `.local` | Documented impossible; require registrable RP ID | Documented |
| Agent auto-approves pairing | Physical-input gate on pair approve | Unit PASS |
| Stolen session cookie | HttpOnly, Secure, SameSite=Strict; revoke kills sessions | Unit PASS |
| Forged Origin / CSRF | Exact Host/Origin allow-list | Unit PASS |
| Enrollment without owner | Single-use enrollment token (5 min) bound to request | Unit PASS |
| Role escalation from phone | New devices = chat only; raise roles on PC + step-up | Unit PASS |
| Password fallback | None — recovery = physical PC access | By design |
| Script access without passkey | Optional `FRIDAY_API_TOKEN` only | Kept |
| DNS rebinding / private DNS filter | PHONE_SETUP nslookup check | Owner manual |

Residual: until hostname+cert, phone mic/passkeys remain unavailable. Playwright WebAuthn adversarial suite still UNVERIFIED.

---

## Model-role table (measured)

| Model | VRAM | Notes |
|-------|------|-------|
| qwen3.5:4b | ~4.5 GB | Fast brain candidate |
| qwen3.5:9b | ~7.1 GB | **Default** main+vision |
| qwen3-vl:8b-instruct | ~7.4 GB | Alternate vision; no clear win |
| qwen2.5vl:7b-q4_K_M | ~7.1 GB | Installed alternate |
| qwen3-coder:30b | spills | On-demand only; never co-resident |
| 4b+9b | ~11 GB | Co-residency viable |
| 9b+3-vl | ~16 GB | Full card |

Ollama 0.30.10: no MTP. Flash-attn/KV: not applied. Defaults unchanged.

---

## Manual steps for the owner

1. **DNS A record** for e.g. `friday.devoids.in` → LAN IP; verify phone + PC `nslookup` (rebinding note in PHONE_SETUP).
2. **DNS-01 certificate** (certbot/lego/etc.) — install ACME client yourself; do not commit keys.
3. Set `.env`: `FRIDAY_AUTH=remote`, `FRIDAY_PUBLIC_HOST=…`, TLS paths; restart Friday.
4. **First device pairing** on PC: matching code + physical approve; then phone WebAuthn create.
5. Raise device roles on the Devices page as needed.
6. **Voice samples** per `docs/VOICE_SAMPLES.md` (STT still provisional).
7. Optional: Ollama service env for flash-attn/q8 KV; optional Tailscale instead of Option A.
8. Optional: `pip install playwright` + virtual authenticator tests.

---

## Defaults changed this run

| Default | Before → After | Why |
|---------|----------------|-----|
| CI workflow | present (never ran) → **removed** | D-031 |
| `FRIDAY_AUTH` | (new) → **`local`** | Passkeys; loopback |
| `FRIDAY_HOST` code default | often 0.0.0.0 in docs → **`127.0.0.1`** until remote | D-032 |
| RequestGuard private Host allow | allowed → **removed** | Exact hosts only |
| `SHELL_TOOLS_ENABLED` | already false; **warn if .env true** | O12 |
| `schedule_task` SAFE | any skill → **reminder only** | D-034 |
| Code `MODEL` fallback | qwen2.5vl… → **`qwen3.5:9b`** | Match reality (R) |
| `FRIDAY_HUMOR` | (new) → **`dry`** | D-037 |
| `FRIDAY_OWNER_NAME` | (new) → **`boss`** | D-037 |
| Model roles / deep / MTP / flash-attn | — | **Not** enabled as defaults |

---

## Decisions made for the owner

D-031 … D-038 in `docs/DECISIONS_NEEDED.md` (remove CI; passkey+loopback; physical pair gate; reminder-only schedule; keep 9b; no Ollama service env; humor dry; deep opt-in).

---

## Installed / needing installation

| Item | Status |
|------|--------|
| `webauthn==2.8.0` (+ cryptography, cbor2) | **Installed** in `friday_env` / pinned in requirements |
| New Ollama models | **None** (forbidden this run) |
| Playwright | **Not** installed — needed for O8 |
| certbot / lego / Tailscale | **Not** installed — owner PHONE_SETUP |
| Ollama flash-attn service flags | **Not** set |

---

## Hard skips

Admin elevation beyond existing, real accounts, money, persistent system changes (Ollama service env, router DNS), merging/pushing, model downloads, long live desktop benches.

---

## Git checkpoints

| Tag | Commit (abbrev) | Topic |
|-----|-----------------|-------|
| `stage-N` | `13bab26` | Remove CI; secrets check |
| `stage-O` | `554e7ff` | Passkey auth |
| `stage-P` | `02705ac` | Model roles research |
| `stage-Q` | `0d2f86d` | Persona / humor / deep / eval |
| `stage-R` | `5085ed2` | Docs sync + pytest + report |

---

## Open risks

- Phone still cannot authenticate until hostname+cert.
- Virtual-authenticator adversarial cases UNVERIFIED.
- Desktop multi-step quality still weak (legacy default).
- Humor dry scored 0.97 on eval (one security-prompt quip slipped the filter once under offline scoring — monitor).
- Owner `.env` may still differ from `.env.example` (e.g. old LAN bind / shell tools) — restart after aligning.
