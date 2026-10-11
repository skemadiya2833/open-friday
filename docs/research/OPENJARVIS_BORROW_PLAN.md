# OpenJarvis borrow plan (Stage V1)

**Source repo (verified):** `https://github.com/open-jarvis/OpenJarvis`  
**Clone path (outside Friday):** `D:\Workspace\_reference\OpenJarvis`  
**Remote check:** `origin` → `https://github.com/open-jarvis/OpenJarvis` (fetch/push)  
**Commit read:** `f9e9d5d28d9e58d7fe601c331fc15a02fad32b2c` (`f9e9d5d chore: update clone traffic data [skip ci]`)  
**License:** Apache License 2.0 — `LICENSE` ends with:

```
Copyright 2025 The OpenJarvis Authors

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0
```

**Read-only:** no OpenJarvis install scripts, no `pip install` of their package, no running their code.

## Modules planned for adaptation

| Stage | OpenJarvis path | License | Friday target | Adapt / strip |
|-------|-----------------|---------|---------------|---------------|
| V2 | `src/openjarvis/agents/loop_guard.py` | Apache-2.0 | `friday/agent/tool_loop_guard.py` (+ wire into tool registry / hybrid) | Port identical-call hash, ping-pong, poll budget in pure Python. **Strip** Rust `_rust_bridge` / EventBus telemetry. |
| V3 | `src/openjarvis/security/scanner.py` | Apache-2.0 | `friday/security/content_scan.py` | Port secret/PII regex patterns + warn/redact/block modes. **Strip** Rust scanner. |
| V3 | `src/openjarvis/security/injection_scanner.py` | Apache-2.0 | same module | Heuristic injection score; default **warn**. |
| V3 | `src/openjarvis/security/taint.py` | Apache-2.0 | `friday/security/taint.py` | Mark untrusted web/fetched text for prompts. |
| V3 | `src/openjarvis/security/credential_stripper.py` | Apache-2.0 | fold into content_scan | Redact before memory/chat store. |
| V3 | `src/openjarvis/security/ssrf.py` | Apache-2.0 | `friday/security/ssrf.py` | Block private/metadata hosts before research fetch. Default **block**. |
| V3 | `src/openjarvis/security/file_policy.py` | Apache-2.0 | `friday/security/file_policy.py` | Sensitive-path deny/warn for file tools + memory ingest. |
| V3 | `src/openjarvis/security/types.py`, `severity_policy.py` (ideas) | Apache-2.0 | light enums in Friday | No SQLite audit — findings → existing hash-chained audit log. **Do not** adapt `security/audit.py` store. |
| V3 | Speech scan idea only | — | voice speak path | Scan **before** TTS (not their post-hoc streaming design). |
| V4 | `src/openjarvis/learning/routing/complexity.py` | Apache-2.0 | `friday/models/complexity.py` | Heuristic complexity score. |
| V4 | `src/openjarvis/learning/routing/heuristic_policy.py` | Apache-2.0 | same + roles wiring | Opt-in `FRIDAY_MODEL_ROLES` / new flag: simple → 4b, hard → 9b. **Do not** adapt `learned_router.py`. |
| V5 | `src/openjarvis/agents/morning_digest.py`, `digest_store.py`, `proactive_agent.py` (patterns) | Apache-2.0 | `friday/briefing/morning.py` + Settings + scheduler job | Local sources only (plan, reminders, weather/news tools). Owner-enabled built-in job. **Strip** Gmail/Calendar OAuth. |
| V6 | `src/openjarvis/telemetry/gpu_monitor.py`, `energy_nvidia.py`, `phase_metrics.py`, `itl.py` (ideas) | Apache-2.0 | `friday/diagnostics/perf.py` + `/api/perf` + Performance UI | Local only. Prefer `nvidia-smi` parse unless a py3.14 Windows NVML wheel exists (check at adapt time). **Strip** analytics network clients (`analytics/client.py`, wandb, sheets). |
| V7 | `src/openjarvis/skills/security.py`, `importer.py` (scan/trust ideas) | Apache-2.0 | extend `friday/skills/agentskills.py` trust | Explicit owner import only; scan instructions/scripts; bind trust to content hash. No community registry bulk import. |
| V8 | design notes from their learning/memory/channels docs | — | `docs/design/*.md` | No code. |

## Explicitly not adapting

- `analytics/client.py`, wandb/sheets trackers (telemetry / phone-home)
- `learned_router.py` (learned router — brief forbids)
- Rust `_rust_bridge` / WASM sandbox (heavy; no py3.14 guarantee)
- Mining / docker / cloud engines
- Their SQLite security audit log (use Friday audit chain)

## Dependencies

Prefer stdlib + existing Friday deps. Any new package requires a **Python 3.14 Windows wheel** before add; otherwise reimplement with stdlib/`subprocess`.

## Notices

Every adapted file gets an Apache-2.0 header (source path, commit, what changed). Aggregate notice: `docs/THIRD_PARTY_NOTICES.md`.
