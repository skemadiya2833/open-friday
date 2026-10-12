# Architecture

Friday is a single-process, local-first assistant on Windows. A FastAPI **Control Center** serves the default web UI (`web/public`) and JSON/SSE/WebSocket APIs. Optional tray and legacy tkinter UIs share the same backend.

## High-level flow

```
Browser / tray  ──HTTP/SSE/WS──►  FastAPI (friday/server)
                                      │
                    assistant orchestrator ◄── tasks scheduler (APScheduler)
                                      │
              intent routing ──► skills (builtin packs) ──► tools (ReAct-lite)
                                      │
              computer_use skill ──► agent loop (observe → decide → one action)
                                      │
              vision capture (mss) + optional Windows-MCP accessibility tree
                                      │
              models (Ollama local, optional cloud fallback)
```

## Major packages

| Area | Location | Role |
|------|----------|------|
| Server & auth | `friday/server`, `friday/auth` | HTTP API, passkey sessions, request guard |
| Assistant | `friday/assistant`, `friday/briefing` | Chat sessions, rhythm, morning/EOD briefings |
| Skills & tools | `friday/skills`, `friday/tools` | Skill router, policy-gated tool registry |
| Agent | `friday/agent`, `friday/vision`, `friday/actions` | Desktop automation loop |
| Hybrid backend | `friday/agent/hybrid.py`, MCP | UIA-first with vision fallback |
| Memory & knowledge | `friday/memory`, `friday/knowledge` | Chroma embeddings, optional private library |
| Calendar | `friday/calendar` | iCal feed (secret URL stored locally, never in repo) |
| Activity & reports | `friday/activity`, `friday/reports` | ActivityWatch hooks, structured research reports |
| Voice | `friday/voice` | STT/TTS pipeline (optional extras) |
| Safety | `friday/safety`, `friday/security` | Approvals, audit chain, SSRF/content scanners |
| Diagnostics | `friday/diagnostics` | Startup validation, doctor/health summaries |

## Process model

- One Python interpreter; long agent runs use worker threads.
- Global singletons include the event bus, model manager, and scheduler — designed for a single interactive user on one machine.
- MCP servers (e.g. Windows-MCP) run as isolated child processes when enabled in `config/mcp_servers.yaml`.

## Data on disk

Runtime state lives under `data/` (gitignored): audit log, memory, conversations, TLS material, calendar secret URL, logs. See `.env.example` and `docs/ENV_FLAGS.md`.

## Security posture (summary)

Loopback-first binding, Host/Origin guard, tiered tool policy, hash-chained audit log, optional API token for non-loopback binds. Details: `docs/THREAT_MODEL.md` and `SECURITY.md`.

## Related docs

- Feature design notes: `docs/design/`
- ADRs: `docs/decisions/`
- Benchmark methods (no raw JSON in repo): `docs/benchmarks.md`
