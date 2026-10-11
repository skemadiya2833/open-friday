# FINAL REPORT 5 — Stages W1–W8 + X1–X2

Branch: `upgrade/research-first`  
No merge, no push. No model downloads. No installers.

## Full test count

| Result | Count | Notes |
|--------|------:|-------|
| **Passed** | **405** | `pytest -q -k "not real_hotkey and not hotkey_conflict and not trigger_log_says"` |
| Failed | 1 | `tests/test_webauthn_virtual.py::test_register_login_stepup_revoke` (Playwright/virtual authenticator env) |
| Deselected | 3 | Real hotkey / estop synthetic tests (desktop hotkey conflict) |
| Collected (unfiltered prior run) | 409 | 405 pass + 4 fail (2 hotkey + 1 trigger_log + 1 webauthn) |

Research-report suite alone: **8 passed** (`test_research_reports` + XSS). Pre-push secrets tests: **4 passed** after notices-hook fix.

## Measured validation rate (W7)

From `docs/research/research_reports_bench.json` (mocked web + mocked model; one fabricated claim per prompt):

| Metric | Value |
|--------|------:|
| Prompts | 10 (quick) |
| Total elapsed | 0.14 s |
| Avg elapsed / prompt | 0.013 s |
| Claims pre-validation | 20 |
| Claims surviving | 10 |
| **Validation survival rate** | **0.5** |

Spot-check sample (20 claim slots): see `spot_check_claims` in that JSON. **Live Ollama 10-prompt run: UNVERIFIED** (not executed in this pass to stay under the 20‑minute live budget; use `python scripts/bench_research_reports.py --live`).

## Status by task

| Task | Status | Evidence |
|------|--------|----------|
| **W1** Study + `research_reports.md` | **PASS** | `docs/design/research_reports.md`; tag `stage-W1` |
| **W2** Report JSON Schema | **PASS** | `friday/reports/schema/report_v1.json` + validators; tag `stage-W2` |
| **W3** Pipeline | **PASS** | `friday/reports/pipeline.py`, `/api/reports/*`, cancel via RunManager; tag `stage-W3` |
| **W4** Renderer / live canvas | **PASS** | `web/public/reports.js` (textContent, SVG DOM, SSE); tag `stage-W4` |
| **W5** Storage / export | **PASS** | `friday/reports/store.py`, MD/HTML export, remember-on-click; tag `stage-W5` |
| **W6** Voice + open-report | **PASS** | research skill TL;DR + intent; tag `stage-W6` |
| **W7** Tests + 10-prompt measure | **PASS** (measure mocked) | tests + bench JSON; live measure **UNVERIFIED** |
| **W8** SearXNG design | **PASS** | `docs/design/searxng_provider.md`; tag `stage-W8` |
| **X1** REFERENCES + README | **PASS** | `docs/REFERENCES.md`, README/CONTRIBUTING links; tag `stage-X1` |
| **X2** Notices consistency check | **PASS** | `scripts/check_third_party_notices.py` wired into pre_push; tag `stage-X2` |

## UNVERIFIED list

1. **Live Ollama 10-prompt quick research** (`bench_research_reports.py --live`) — not run this pass.
2. **End-to-end UI research canvas** against a running server (SSE + progressive cards) — unit/Playwright XSS only.
3. **WebAuthn virtual authenticator** full register/login/step-up/revoke — failed in this environment.
4. **Real e-stop hotkey** injection tests — deselected / failed when hotkey already registered.
5. **Deep/think mode quality** on real web pages — pipeline exists; quality not scored live.
6. **Dig-deeper merge** beyond creating a new quick sub-report — no separate live bench.
7. **Phone/mobile layout** for Reports view — CSS present; no device lab run.
8. **SearXNG** — design only; not installed.

## Dependencies added

**None.**

## Manual steps for the owner

1. Open Control Center → **Reports**; tools-role device to run web research; chat role can view history.
2. Try “research report: …” in Comms or the Reports form (quick/deep/think).
3. Cancel via the Reports Cancel button or e-stop; confirm run stops.
4. Export Markdown/HTML; optional **Remember findings**.
5. Spot-check `docs/research/research_reports_bench.json` claims; optionally run `--live`.
6. Review `docs/REFERENCES.md` and `docs/THIRD_PARTY_NOTICES.md`.
7. Before any push: `python scripts/pre_push_secrets_check.py` (includes notices check).
8. Do **not** merge/push until you review tags `stage-W1`…`stage-W8`, `stage-X1`, `stage-X2`.

## Tags

`stage-W1` … `stage-W8`, `stage-X1`, `stage-X2` on `upgrade/research-first`.
