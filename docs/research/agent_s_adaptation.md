# Experience memory: design, source and license

## Source adapted
Agent S (simular-ai/Agent-S, **Apache-2.0**, checked via the GitHub API). Read: `gui_agents/s2/core/knowledge.py`
(KnowledgeBase: `narrative_memory.json` = task-level summaries, `episodic_memory.json` = subtask-level steps,
cosine retrieval over cached embeddings, an LLM that summarises a finished trajectory, a self-evaluation step).
No Agent S code is copied or vendored; only the two-level idea is reused.

## What we kept / changed
| Agent S | Friday |
|---|---|
| narrative (task) + episodic (subtask) memory | same split, two Chroma collections `exp_narrative`, `exp_episodic` in `data/experience/chroma` |
| JSON files + pickled embeddings | Chroma (cosine) with metadata: provenance, source, confidence, created_at, hit_count, apps, enabled |
| LLM writes the summaries | deterministic summaries from structured trajectories (no extra model call, no prompt-injection path) |
| model self-evaluation decides what is stored | objective check first (confidence 0.95); self-judgment is low confidence (0.4) and not retrieved by default |
| retrieves the single best entry | top-k per collection, similarity floor, confidence floor, token cap, fenced "DATA ONLY" block |
| no safety model | memory is data: it cannot touch the guard, allow/deny lists or approvals; injection-like entries are skipped; no learning from web pages unless success was objectively verified |

## Modes
`FRIDAY_MEMORY` = `off` (default) | `record` (learn only) | `read` (hints only) | `on` (both). Everything is local.

## Owner controls
`/experience` page + `/api/experience*`: view, edit (owner edit raises confidence), delete, disable per entry, per-app
switch, growth limits (max entries, trajectories, retention days, confidence floor, token cap), export, and
"propose skills" (creates *proposals* in the existing skill approval workflow; never auto-enabled).
