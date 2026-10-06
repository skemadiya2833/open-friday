# LoRA / QLoRA fine-tuning feasibility (research only, nothing built)

Target: a 7-9B vision-language model (Qwen2.5-VL-7B or Qwen3-VL-8B) on an RTX 5060 Ti, 16 GB, compute capability 12.0.

**Memory estimate (not measured here):** 4-bit base weights ~5-6 GB, vision tower kept in bf16 ~1.3 GB, LoRA rank 16
adapters + optimizer states < 1 GB, activations with gradient checkpointing at 2-4k tokens and 1 image per sample,
batch 1: ~4-6 GB. Total ~11-14 GB, so QLoRA at batch size 1 with gradient accumulation *should* fit; long
multi-image sequences and the 1120x630 screenshots used by the agent are the risk (image tokens dominate). Full
LoRA in bf16 (weights ~15 GB) does not fit.

**Tooling state on this machine:** torch, transformers, peft, trl, bitsandbytes and unsloth are NOT installed in
`friday_env`. Blackwell (sm_120) needs a CUDA 12.8+ PyTorch build (>= 2.7) and a bitsandbytes build that supports it:
UNVERIFIED. Python 3.14 wheels for this stack may not exist yet; a separate Python 3.11/3.12 environment would be
needed. Unsloth advertises Qwen2.5-VL support; also UNVERIFIED here.

**Serving the result:** Ollama can apply a LoRA through a Modelfile `ADAPTER`, but only for architectures llama.cpp
converts; vision-language adapters for Qwen2.5-VL/Qwen3-VL are not confirmed. Merging then converting to GGUF is the
fallback. UNVERIFIED.

**Data is the real blocker.** Recorded trajectories contain no screenshots (by design). Training a vision model needs
(observation image, action) pairs: hundreds to thousands of *objectively verified* successes. Today there are tens.
A separate opt-in screenshot recorder (local only, retention-limited, with a redaction pass) would be required.

**Risks:** overfitting to the 26 benchmark tasks (must evaluate on the frozen held-out split), forgetting general
ability, and learning from attacker-controlled page content (only train on `judgment=objective`, `untrusted_source=false`).

**Recommendation:** do not fine-tune yet. First collect verified trajectories via `FRIDAY_MEMORY=record`, measure
whether retrieval memory helps (Stage L7), and only then consider a QLoRA pilot in a separate environment.
