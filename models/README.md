# Local models

Friday talks to models through **Ollama**. On a **16 GB** GPU use one multimodal tag for chat and screen look — do not pair a text-only 27B GGUF with a separate VL (VRAM thrash + double disk).

## Recommended (16 GB)

| Role | Model | Notes |
|------|--------|--------|
| Chat / tools / screen / camera | `qwen3-vl:8b-instruct` | Ollama Q4_K_M · vision + tools · native 256K (use `CHAT_NUM_CTX=32768` so KV fits) |

```powershell
ollama pull qwen3-vl:8b-instruct
```

At 32K context, weights + KV sit around ~10 GB — headroom left on an RTX 16 GB card. 64K is near the ceiling; full 256K does not fit.

## Do not use for Friday “look”

Text-only GGUFs (e.g. Unsloth `Qwen3.8-27B-UD-IQ3_*`) have no vision projector. Sending screenshots to them returns Ollama **500**.
