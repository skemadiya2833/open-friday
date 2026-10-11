# FINAL REPORT 4 — Stages V1–V8 (OpenJarvis borrow)

Branch: `upgrade/research-first`  
Reference: [open-jarvis/OpenJarvis](https://github.com/open-jarvis/OpenJarvis) @ `f9e9d5d28d9e58d7fe601c331fc15a02fad32b2c` (Apache-2.0)  
Clone (read-only, outside Friday repo): `D:\Workspace\_reference\OpenJarvis`  
Remote verified: `https://github.com/open-jarvis/OpenJarvis`  
No merge, no push. No model downloads. No installers.

## Status by stage

| Stage | Task | Status | Evidence |
|-------|------|--------|----------|
| **V1** | Provenance / license plan | **PASS** | `docs/research/OPENJARVIS_BORROW_PLAN.md`, `docs/THIRD_PARTY_NOTICES.md`; tag `stage-V1` |
| **V2** | Loop guard (repeated-call / ping-pong / no-change) | **PASS** | `friday/agent/tool_loop_guard.py` + tests; tag `stage-V2` |
| **V3** | Content security wired + adversarial tests | **PASS** | `friday/security/*`, research/memory/files/TTS hooks, audit JSONL; 7 tests; tag `stage-V3` |
| **V4** | Complexity routing opt-in | **PASS** | `friday/models/complexity.py`, `FRIDAY_COMPLEXITY_ROUTING`; blend bench keeps 9b default; tag `stage-V4` |
| **V5** | Local morning briefing | **PASS** | `friday/briefing/morning.py`, Settings + `/api/briefing/morning*`; agents cannot schedule; tag `stage-V5` |
| **V6** | Performance / energy panel | **PASS** | `friday/perf.py`, `/api/perf`, `/health` panel; nvidia-smi (no new dep); tag `stage-V6` |
| **V7** | Skill import scanning | **PASS** | `friday/skills/skill_security.py` enriching `review()`; hash trust unchanged; tag `stage-V7` |
| **V8** | Design notes only | **PASS** | `docs/design/*.md` (4 + OAuth note); tag `stage-V8` |

## Adapted files (source → Friday)

| Friday | OpenJarvis source | Commit |
|--------|-------------------|--------|
| `friday/agent/tool_loop_guard.py` | `src/openjarvis/agents/loop_guard.py` | f9e9d5d… |
| `friday/security/ssrf.py` | `src/openjarvis/security/ssrf.py` | f9e9d5d… |
| `friday/security/file_policy.py` | `src/openjarvis/security/file_policy.py` | f9e9d5d… |
| `friday/security/content_scan.py` | `src/openjarvis/security/scanner.py` (+ ideas) | f9e9d5d… |
| `friday/security/taint.py` | `src/openjarvis/security/taint.py` (ideas) | f9e9d5d… |
| `friday/models/complexity.py` | `learning/routing/complexity.py` (+ heuristic select) | f9e9d5d… |
| `friday/briefing/morning.py` | `tools/digest_collect.py` (pattern; no OAuth) | f9e9d5d… |
| `friday/perf.py` | `telemetry/gpu_monitor.py` (+ energy/phase ideas) | f9e9d5d… |
| `friday/skills/skill_security.py` | `skills/security.py` (+ importer ideas) | f9e9d5d… |

Headers + aggregate notice: `docs/THIRD_PARTY_NOTICES.md`.

## Dependencies added

**None.** nvidia-ml-py has a `py3-none-any` wheel but was **not** added; GPU samples use `nvidia-smi` (optional pynvml only if already installed).

## Telemetry-like items removed / never copied

- OpenJarvis `analytics/client.py`, wandb/sheets trackers — **not adapted**
- Their SQLite security audit store — **not adapted**; findings go to Friday hash-chained `tool_calls.jsonl`
- Network phone-home in adapted modules — stripped / never present
- Gmail/Calendar OAuth connectors — **not adapted** (design note only)

## Defaults kept

- Chat model: **qwen3.5:9b** (complexity routing opt-in; blend bench: routed correctness 0.975 vs 9b 1.0 → keep 9b)
- Secrets mode: redact; SSRF: block; injection: warn
- Morning briefing: **off** until owner enables in Settings

## Manual steps for the owner

1. Review `docs/research/OPENJARVIS_BORROW_PLAN.md` and `docs/THIRD_PARTY_NOTICES.md`.
2. Optional: set `FRIDAY_COMPLEXITY_ROUTING=true` after reading `docs/research/complexity_routing_bench.json`.
3. Settings → Morning briefing → enable (or `FRIDAY_MORNING_BRIEFING=true`); “Run once now” to sample.
4. Open `/health` for the Performance panel (VRAM/power via nvidia-smi).
5. Skill import remains inbox → quarantine → approve with content hash (never auto-enable).
6. Do **not** merge/push this branch until you review tags `stage-V1` … `stage-V8`.

## Tags

`stage-V1` … `stage-V8` on `upgrade/research-first`.
