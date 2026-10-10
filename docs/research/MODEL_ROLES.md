# Model roles (Stage P) — measured on this PC

**Date:** 2026-10-10  
**Ollama:** **0.30.10** — MTP speculative decoding (docs: ≥0.32 / mainly MLX) **not available**; not enabled.  
**GPU:** RTX 5060 Ti 16 GB  
**Raw:** [`model_roles_bench.json`](model_roles_bench.json)  
**Default unchanged:** unified `qwen3.5:9b`. Set `FRIDAY_MODEL_ROLES=true` only after reviewing this table.

## Latency & VRAM

| Model | VRAM after load | Load+greet wall | Tool JSON ok | Plan JSON ok | Notes |
|-------|-----------------|-----------------|--------------|--------------|-------|
| qwen3.5:4b | **4498 MB** | 7.4 s | yes (~2.9 s) | yes (~2.7 s) | Fastest resident; tool sample ignored schema fields somewhat |
| qwen3.5:9b | **7092 MB** | 9.3 s | yes (~2.9 s) | yes (~2.9 s) | Current default |
| qwen3-vl:8b-instruct | **7412 MB** | 13.8 s | yes (~2.8 s) | yes (~2.5 s) | Good structured; slower load |
| qwen2.5vl:7b-q4_K_M | **7108 MB** | 8.6 s | yes (~2.6 s) | yes (~2.5 s) | Solid structured |
| qwen3-coder:30b | ~14–16 GB class | **27 s**, empty sample | fail/empty | — | Spill / contention; not for co-residency |

Greet prompts requested plain text while the harness forced JSON format — greet `chars=0` is a harness quirk, not a model failure. Structured rows are the reliable signal.

## Co-residency (observational)

| Pair | VRAM trajectory |
|------|-----------------|
| 4b then 9b | 623 → 4494 → **10965 MB** — both can sit with headroom |
| 9b then 3-vl | 4494 → 10969 → **15962 MB** — essentially full card |

## Recommendations

1. **Keep default `qwen3.5:9b`.**
2. Optional fast brain: `qwen3.5:4b` for greetings/routing when `FRIDAY_MODEL_ROLES=true`.
3. Vision alternate: `qwen3-vl:8b-instruct` is viable but no clear win over 9b on these micro-tasks.
4. **Never** leave `qwen3-coder:30b` resident with others; on-demand text/tree only.
5. Prompt order: static system + tools first, screen last (cache-friendly).
6. `OLLAMA_FLASH_ATTENTION` + `OLLAMA_KV_CACHE_TYPE=q8_0`: must be set on the Ollama **service** — **not applied** (would be a persistent system change). UNVERIFIED.
7. Windows build **26300**; on-device MCP / Agent Workspace preview — research only, **not enabled**.

## Opt-in env

```
FRIDAY_MODEL_ROLES=false
FRIDAY_MODEL_FAST=qwen3.5:4b
FRIDAY_MODEL_MAIN=qwen3.5:9b
FRIDAY_MODEL_VISION=qwen3.5:9b
FRIDAY_MODEL_CODER=qwen3-coder:30b
```
