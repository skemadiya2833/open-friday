# Memory extraction & session compression vs Friday today

## Friday today

- Notes / facts via memory store (Chroma) + automemory heuristics.
- Chat history persisted per session JSON under `data/conversations/`.
- Experience store for desktop patterns; day plan in `today_plan.json`.
- Secrets redacted before memory writes (Stage V3).

## OpenJarvis-style extraction / compression (not adapted as code)

They emphasize structured extraction of durable facts from long sessions and compressing older turns into summaries so the active context stays short.

## Fit

| Idea | Friday fit |
|------|------------|
| Extract durable owner facts | Aligns with automemory; keep owner-visible + forgettable |
| Compress old turns | Useful for long voice sessions; should be opt-in and show the summary |
| Cross-session digests | Overlaps morning briefing; keep local-only |

## Recommendation

Keep Friday's explicit memory tools and hash-chained audit. If compression is added later, store the summary as a first-class note the owner can edit/delete, never silent rewrite of raw history.
