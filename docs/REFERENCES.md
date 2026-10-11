# Credits and references

Licenses recorded as read from each project’s `LICENSE` (or published docs) at the time of Stage X (2026-10-11). “Ideas only” means no source was copied into Friday.

| Name | URL | License | What Friday took | Version / commit |
|------|-----|---------|------------------|------------------|
| **OpenJarvis** | https://github.com/open-jarvis/OpenJarvis | Apache-2.0 | **Code adapted** (loop guard, security scanners, complexity routing, briefing/perf ideas, research loop patterns). See `docs/THIRD_PARTY_NOTICES.md`. | `f9e9d5d28d9e58d7fe601c331fc15a02fad32b2c` |
| **Windows-MCP** | https://github.com/CursorTouch/Windows-MCP | Apache-2.0 (upstream README) | **Runtime tool** via MCP (pinned `windows-mcp==0.8.7`); disabled by default. | 0.8.7 |
| **Hermes Agent** | https://github.com/NousResearch/hermes-agent (and related Hermes skill docs) | Check upstream LICENSE at use time | **Skill format / design idea** for modular skills; Friday’s skill runtime is original. | ideas (pin not vendored) |
| **agentskills.io** | https://agentskills.io | Spec (see site) | **Skill format** (`SKILL.md` frontmatter, progressive disclosure). Spec snapshot `docs/research/raw/agentskills-spec.md` (2026-10-06). | spec fetched 2026-10-06 |
| **A2UI** | https://a2ui.org / https://github.com/google/A2UI | Apache-2.0 | **Design pattern**: fixed component catalog, declarative UI JSON, progressive fill. Friday uses its own report schema — not the A2UI wire format. | v0.9.1 family (docs) |
| **AG-UI** | https://github.com/ag-ui-protocol/ag-ui (ecosystem with A2UI) | Apache-2.0 (typical; verify at use) | **Design pattern**: agent↔UI event transport ideas. No AG-UI SDK vendored. | ideas only |
| **Local Deep Research** | https://github.com/LearningCircuit/local-deep-research | MIT | **Pipeline ideas**: question → search → synthesize; optional SearXNG. No code copied. | docs/main @ study time |
| **GPT Researcher** | https://github.com/assafelovic/gpt-researcher | Apache-2.0 | **Pipeline ideas**: planner questions + source-tracked report. No code copied. | master LICENSE @ study |
| **STORM** | https://github.com/stanford-oval/storm | MIT | **Pipeline ideas**: multi-perspective questions, outline-then-write with citations. No code copied. | main LICENSE @ study |
| **UFO2** | paper / Microsoft UFO line (see `docs/research/raw/ufo-README.md`) | Unclear / research | **Ideas only, no code copied** | paper/ideas |
| **Agent S** | https://github.com/simular-ai/Agent-S (see `docs/research/agent_s_adaptation.md`) | Check LICENSE at use | **Ideas only, no code copied** (desktop agent patterns) | ideas |
| **VLAA-GUI** | research paper / project pages | Unclear | **Ideas only, no code copied** | paper/ideas |
| **AgentSynth** | research paper / project pages | Unclear | **Ideas only, no code copied** | paper/ideas |
| **Qwen / Qwen3.5** (Alibaba) | https://github.com/QwenLM | Apache-2.0 (model cards / repos vary by artifact) | **Models** run via Ollama (`qwen3.5:9b`, `qwen3.5:4b`, vision variants) — not redistributed in this repo. | tags as installed locally |
| **Ollama** | https://ollama.com | MIT | **Runtime** for local inference. | 0.30.10 noted in research |
| **nomic-embed-text** | Nomic AI / Ollama library | Check model card | **Embedding model** via Ollama. | as installed |

Also see: `docs/THIRD_PARTY_NOTICES.md` (adapted-file inventory), `docs/design/research_reports.md` (W1 study).
