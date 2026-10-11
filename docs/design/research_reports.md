# Research reports — what to adapt (Stage W1)

Read-only study. No installs. OpenJarvis clone verified at
`D:\Workspace\_reference\OpenJarvis` remote `https://github.com/open-jarvis/OpenJarvis`
commit `f9e9d5d28d9e58d7fe601c331fc15a02fad32b2c`.

## Sources

| Project | URL | License (as read) | What Friday takes |
|---------|-----|-------------------|-------------------|
| **OpenJarvis** deep research / research router | github.com/open-jarvis/OpenJarvis | Apache-2.0 (`LICENSE` @ f9e9d5d) | **Ideas + light patterns**: planner→search→synthesize loop, SSE progress events (`search_call` / `search_result` / `synthesis` / `done`). Not their personal-KB tools or clarify stdin. |
| **Local Deep Research** | github.com/LearningCircuit/local-deep-research | MIT (`LICENSE` on main / PyPI) | **Ideas only**: strategy modes, question generation → search → report synthesis, optional SearXNG provider. No code copied. |
| **GPT Researcher** | github.com/assafelovic/gpt-researcher | Apache-2.0 (`LICENSE`) | **Ideas only**: planner questions + parallel gather + source-tracked aggregation into a cited report. No code copied. |
| **STORM** (Stanford) | github.com/stanford-oval/storm | MIT (`LICENSE`) | **Ideas only**: multi-perspective question asking, outline then write with citations. No code copied. |
| **A2UI** | a2ui.org / github.com/google/A2UI (a2ui-project) | Apache-2.0 | **Design pattern**: fixed component catalog, declarative JSON (not executable UI), progressive streaming, client-owned renderer. Friday uses its **own** report schema (not A2UI wire format). |

## Attribution rules

1. Any **adapted Python** from OpenJarvis needs Apache-2.0 header + `docs/THIRD_PARTY_NOTICES.md` entry (same as Stages V).
2. **Ideas-only** projects: document in `docs/REFERENCES.md`; do **not** copy source files.
3. A2UI: catalog + progressive fill is inspirational; renderer is vanilla JS under Friday HUD theme — no A2UI SDK, no CDN.
4. Prefer Friday existing stack: `web_search` + V3 SSRF/scanners, Ollama structured outputs, per-run events, auth roles (`chat` view / `tools` run).

## Friday shape (W2–W7)

- Versioned JSON Schema with fixed components (summary, findings, tables, charts, claims, sources, …).
- Mechanical citation validation (exact substring evidence).
- Modes: quick ≤4 sources, deep ≤12, think (no web unless asked).
- Live canvas over existing event stream; safe DOM (`textContent` only).
- Storage under `data/reports` with export; speak TL;DR only.

## Explicitly not adapting

- OpenJarvis private knowledge_sql / connector digests for this feature.
- LDR LangGraph agent / encrypted SQLCipher stack.
- GPT Researcher Tavily/cloud defaults or image generation.
- STORM dspy modules.
- A2UI Angular/Flutter/Lit renderers.
