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

## Do not use for Friday “look”

Text-only GGUFs (e.g. Unsloth `Qwen3.8-27B-UD-IQ3_*`) have no vision projector. Sending screenshots to them returns Ollama **500**.
