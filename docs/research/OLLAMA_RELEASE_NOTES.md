# Ollama release notes (research only — do not update)

**Installed on this PC:** **0.30.10** (`ollama --version`, 2026-10-10).

This file lists *newer* upstream themes that may help Friday later. **Do not upgrade Ollama in this run.**

Sources: Ollama GitHub releases / blog notes referred in Stage P research (not re-fetched as a live scrape this pass — treat versions as indicative).

| Theme | Approx. release line | Relevance to Friday |
|-------|----------------------|---------------------|
| Structured outputs / JSON schema | Improved across 0.3x; thinking-model schema hardening in later 0.3x | Already used via `format_schema` on 0.30.10; newer builds may reduce empty/malformed plans |
| Prompt caching | Recent 0.3x notes | Keep static system+tools first, screen last (already the design) |
| MTP speculative decoding | Notes cite **≥0.32.x**, mainly Apple **MLX** | **Not available** on 0.30.10 CUDA Windows; do not enable until measured on a newer build |
| Flash attention + KV quant (q8_0) | Service env (`OLLAMA_FLASH_ATTENTION`, `OLLAMA_KV_CACHE_TYPE`) | Persistent system change — owner opt-in only (D-036) |
| Multi-model / keep_alive | Ongoing | Use `OLLAMA_MAX_LOADED_MODELS` + `keep_alive` when enabling roles |

**Recommendation:** stay on 0.30.10 until the owner schedules an upgrade window; re-run `scripts/bench_model_roles.py` and `scripts/bench_parse_schema.py` after any upgrade.
