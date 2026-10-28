# Third-party notices

## OpenJarvis (Apache-2.0)

- **Project:** [open-jarvis/OpenJarvis](https://github.com/open-jarvis/OpenJarvis)
- **License:** Apache License 2.0
- **Copyright:** Copyright 2025 The OpenJarvis Authors
- **Commit adapted from:** `f9e9d5d28d9e58d7fe601c331fc15a02fad32b2c`
- **Local clone (read-only reference):** `D:\Workspace\_reference\OpenJarvis`
- **Borrow plan:** `data/benchmarks/OPENJARVIS_BORROW_PLAN.md`

Portions of Friday listed below are derived from OpenJarvis source under Apache-2.0.
Each adapted Python file carries a header with the source path, license, and a short
description of changes. Original copyright notices are preserved.

| Friday file | OpenJarvis source | Stage |
|-------------|-------------------|-------|
| `friday/agent/tool_loop_guard.py` | `src/openjarvis/agents/loop_guard.py` | V2 |
| `friday/security/ssrf.py` | `src/openjarvis/security/ssrf.py` | V3 |
| `friday/security/file_policy.py` | `src/openjarvis/security/file_policy.py` | V3 |
| `friday/security/content_scan.py` | `src/openjarvis/security/scanner.py` (+ injection / stripper ideas) | V3 |
| `friday/security/taint.py` | `src/openjarvis/security/taint.py` (ideas) | V3 |
| `friday/models/complexity.py` | `src/openjarvis/learning/routing/complexity.py` (+ heuristic select from `router.py`) | V4 |
| `friday/briefing/morning.py` | `src/openjarvis/tools/digest_collect.py` (sectioned digest pattern; no OAuth connectors) | V5 |
| `friday/perf.py` | `src/openjarvis/telemetry/gpu_monitor.py` (+ energy/phase ideas); **no** analytics clients | V6 |
| `friday/skills/skill_security.py` | `src/openjarvis/skills/security.py` (+ importer trust ideas) | V7 |

Full Apache-2.0 text: see the `LICENSE` file in the OpenJarvis repository at the commit above,
or <http://www.apache.org/licenses/LICENSE-2.0>.

---

## Cua Driver (MIT) — wrapped MCP

- **Project:** [trycua/cua](https://github.com/trycua/cua) · [cua.ai/docs/cua-driver](https://cua.ai/docs/cua-driver)
- **License:** MIT (Cua Driver)
- **Use in Friday:** Optional MCP server `cua` in `config/mcp_servers.yaml`, gated by Systems pref `cua_enabled`. Friday does not vendor Cua source; the owner installs `cua-driver` separately.

## Google Artemis (Apache-2.0) — wrapped MCP

- **Project:** [google/artemis](https://github.com/google/artemis)
- **License:** Apache License 2.0 (includes third_party notices upstream)
- **Use in Friday:** Optional MCP server `artemis` in `config/mcp_servers.yaml`, gated by Systems pref `artemis_enabled`. Friday clones into `data/vendor/artemis` on enable (not checked into this repo). Needs ADB + Android device/emulator and a multimodal API key (`GOOGLE_API_KEY` / `GEMINI_API_KEY`). Launcher: `scripts/artemis_mcp.py`.

## OpenClaw / ClawHub / Hermes Agent — skill format (MIT / check per-skill)

- **Projects:** [openclaw/openclaw](https://github.com/openclaw/openclaw), [clawhub.ai](https://clawhub.ai), [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent)
- **Use in Friday:** agentskills.io `SKILL.md` inbox → quarantine → hash-bound install (`friday/skills/agentskills.py`). Optional HTTPS/git fetch into inbox when `skill_hub_fetch` is on. Individual imported skills retain their own licenses — credit them in the skill folder.

## ZYRON — Telegram remote pattern (MIT)

- **Project:** [Surajkumar5050/zyron-assistant](https://github.com/Surajkumar5050/zyron-assistant)
- **Use in Friday:** Native long-poll Bot API channel (`friday/channels/telegram.py`). Token lives in Systems as a secret pref. Architecture inspired by ZYRON’s phone-remote idea; code is Friday-native.

## Presence / HUD working bubble — ideas

- **Inspiration:** DesktopClaw ([varun86/DesktopClaw](https://github.com/varun86/DesktopClaw)), jarvis-py HUD ([Shaan-alpha/jarvis-py](https://github.com/Shaan-alpha/jarvis-py))
- **Use in Friday:** Native HUD orb + request-scoped working bubble (`presence_orb` pref). No Electron pet fork.

## Voice latency — architecture only (no AGPL vendor)

- **Inspiration:** alexberardi/jarvis (AGPL server) — stream LLM→TTS, keep model warm
- **Use in Friday:** Ollama `keep_alive` + existing barge-in speaker pipeline. We do **not** vendor AGPL server code.

## Plan approve / versioning — ideas

- **Inspiration:** porokka/jarvis-os plan runner
- **Use in Friday:** Native `friday/plans/` store with approve / rerun versioning for multi-step jobs.
