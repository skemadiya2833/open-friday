# Credits and references

Licenses recorded as read from each project’s `LICENSE` (or published docs) at integration time. “Ideas only” means no source was copied into Friday.

| Name | URL | License | What Friday took | Version / commit |
|------|-----|---------|------------------|------------------|
| **OpenJarvis** | https://github.com/open-jarvis/OpenJarvis | Apache-2.0 | **Code adapted** (loop guard, security scanners, complexity routing, briefing/perf ideas, research loop patterns). See `docs/THIRD_PARTY_NOTICES.md`. | `f9e9d5d28d9e58d7fe601c331fc15a02fad32b2c` |
| **Windows-MCP** | https://github.com/CursorTouch/Windows-MCP | Apache-2.0 (upstream README) | **Runtime tool** via MCP (pinned `windows-mcp==0.8.7`); disabled by default. | 0.8.7 |
| **Hermes Agent** | https://github.com/NousResearch/hermes-agent | Check upstream LICENSE | **Skill format / design idea** for modular skills; Friday’s skill runtime is original. | ideas (not vendored) |
| **Agent Skills spec** | https://agentskills.io | Spec (see site) | **Skill format** (`SKILL.md` frontmatter, progressive disclosure). | spec as published |
| **A2UI** | https://a2ui.org / https://github.com/google/A2UI | Apache-2.0 | **Design pattern**: fixed component catalog, declarative UI JSON. Friday uses its own report schema. | v0.9.x family (docs) |
| **AG-UI** | https://github.com/ag-ui-protocol/ag-ui | Apache-2.0 (verify at use) | **Design pattern**: agent↔UI event transport ideas. No AG-UI SDK vendored. | ideas only |
| **Local Deep Research** | https://github.com/LearningCircuit/local-deep-research | MIT | **Pipeline ideas**: question → search → synthesize; optional SearXNG. No code copied. | study time |
| **GPT Researcher** | https://github.com/assafelovic/gpt-researcher | Apache-2.0 | **Pipeline ideas**: planner questions + source-tracked report. No code copied. | study time |
| **STORM** | https://github.com/stanford-oval/storm | MIT | **Pipeline ideas**: multi-perspective questions, outline-then-write with citations. No code copied. | study time |
| **Microsoft UFO** | https://github.com/microsoft/UFO | MIT | **Ideas only** (hybrid UIA + vision desktop agent). | upstream README |
| **Agent S** | https://github.com/simular-ai/Agent-S | Check LICENSE | **Ideas only** (desktop agent patterns). | ideas |
| **openWakeWord** | https://github.com/dscripka/openWakeWord | Apache-2.0 | Wake-word ONNX path (optional). | upstream releases |
| **Model Context Protocol Python SDK** | https://github.com/modelcontextprotocol/python-sdk | MIT | MCP client (`mcp` package). | v2.x (see ADR-0006) |
| **Fara** | https://github.com/microsoft/fara | MIT | Browser automation research (evaluate if servable). | upstream README |
| **Qwen / Qwen3.5** (Alibaba) | https://github.com/QwenLM | Apache-2.0 (model cards vary) | **Models** via Ollama — not redistributed in this repo. | local Ollama tags |
| **Arwes** | https://github.com/arwes/arwes | MIT | **Ideas only** — sci-fi HUD framing; see `docs/design/hud.md`. | ideas only |
| **Ollama** | https://ollama.com | MIT | **Runtime** for local inference. | as installed |
| **nomic-embed-text** | Nomic AI / Ollama library | Check model card | **Embedding model** via Ollama. | as installed |
| **Open WebUI** | https://github.com/open-webui/open-webui | BSD-3-Clause (verify) | **Ideas only**: admin/metrics panels, env-driven toggles. | survey |
| **Home Assistant** | https://github.com/home-assistant/core | Apache-2.0 | **Ideas only**: consolidated ops state. | survey |
| **Leon** | https://github.com/leon-ai/leon | GPL-3.0 (verify) | **Ideas only**: skill/status overview — no code copied. | survey |
| **OpenClaw** | https://github.com/openclaw/openclaw | Check upstream | **Ideas only**: pre-flight before agent runs. | survey |
| **OpenVoiceOS (OVOS)** | https://github.com/OpenVoiceOS/OVOS | Apache-2.0 (typical) | **Ideas only**: readiness messaging. | survey |

Also see: `docs/THIRD_PARTY_NOTICES.md`, `docs/design/research_reports.md`, `docs/ENV_FLAGS.md`.
