# Local models

Friday talks to models through **Ollama**. On a **16 GB** GPU use one multimodal tag for chat and screen look — do not pair a text-only GGUF with a separate VL (VRAM thrash + double disk).

## Recommended (16 GB)

| Role | Model | Notes |
|------|--------|--------|
| Chat / tools / screen / camera | `gemma4:12b` | Ollama Q4_K_M · vision + tools · ~8 GB weights · native 256K (use `CHAT_NUM_CTX=32768` so KV fits) |

```powershell
ollama pull gemma4:12b
```

Fallback if you prefer the prior VL: `qwen3-vl:8b-instruct`.

At 32K context, weights + KV should fit an RTX 16 GB card with some headroom. Full 256K does not.

## Optional unified brain: Underdog Saluki 27B (+ mmproj)

[Saluki](https://underdog.ai/saluki) is a ~7.9 GB 2-bit Qwen3.8-27B GGUF (tool calling). The main file is **text-only**; vision needs the separate **mmproj** (~0.6–0.9 GB).

**16 GB rule (this machine):** do **not** pair Saluki with a second VL (`gemma4` / `qwen3-vl`). Either:

1. One Ollama tag `saluki` built from **main GGUF + mmproj**, and set **both** Chat and Vision to `saluki`, or  
2. Skip Saluki and stay on `gemma4:12b` (or another single multimodal).

```powershell
# Needs Ollama 0.40+. Downloads ~8.5 GB once, creates multimodal tag.
.\scripts\setup_saluki.ps1
```

Custom mmproj + Qwen3.5-family in Ollama is **experimental**. If `ollama create` / run fails, Saluki is out — do not fall back to “Saluki text + other VL”.

## Do not use for Friday “look”

A text-only GGUF (Saluki **without** mmproj, Unsloth text quants, etc.) has no vision projector. Screenshots → Ollama **500**.
