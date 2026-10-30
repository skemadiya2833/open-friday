# Local models

Friday talks to models through **Ollama**. On a **16 GB** GPU use **one multimodal tag** for chat and screen/camera look — do not pair a text-only GGUF with a separate VL (VRAM thrash + reload delay).

Project handoff: [`CONTEXT.md`](../CONTEXT.md). Install overview: [`README.md`](../README.md).

## Recommended (16 GB)

| Role | Model | Notes |
|------|--------|--------|
| Chat / tools / screen / camera | `saluki:latest` **or** `gemma4:12b` | Set **both** Systems chat & vision to the same tag |
| Embeddings | `nomic-embed-text` | Memory |

```powershell
ollama pull gemma4:12b
ollama pull nomic-embed-text
```

### Resident context (do not thrash)

Ollama reloads the GPU resident when `num_ctx` changes between calls. Friday pins one size via `resolve_resident_num_ctx()`:

| Setting | Typical |
|---------|---------|
| Shared chat+vision default | **8192** (`FRIDAY_MAX_SHARED_CTX`, unless `FRIDAY_RESIDENT_NUM_CTX` is set) |
| Saluki Modelfile | `PARAMETER num_ctx 8192` (also `temperature 0.6`, `top_p 0.95`, `top_k 20`) |

Keep Systems chat/vision on the same tag so `after_vision` does not unload/reload.

## Optional unified brain: Underdog Saluki 27B (+ mmproj)

[Saluki](https://underdog.ai/saluki) is a ~7.9 GB 2-bit Qwen3.8-27B GGUF (tools + thinking). The main file is **text-only** without the projector; vision needs **mmproj** (~0.6–0.9 GB).

**16 GB rule:** do **not** pair Saluki with a second VL (`gemma4` / `qwen3-vl`). Either:

1. One Ollama tag `saluki` built from **main GGUF + mmproj**, and set **both** Chat and Vision to `saluki`, or  
2. Skip Saluki and stay on `gemma4:12b` (or another single multimodal).

```powershell
# Needs Ollama 0.40+. Downloads ~8.5 GB once, creates multimodal tag.
.\scripts\install_saluki.ps1
# or from models/saluki:
#   ollama create saluki -f Modelfile
```

Modelfile lives at [`models/saluki/Modelfile`](saluki/Modelfile).

Custom mmproj + Qwen3.5-family in Ollama is **experimental**. If `ollama create` / run fails, Saluki is out — do not fall back to “Saluki text + other VL”.

## Fallbacks

| Tag | When |
|-----|------|
| `qwen3-vl:8b-instruct` | Smaller VL if Gemma/Saluki unavailable |
| `qwen3.5:9b` | Text-leaning hybrid only if the tag is vision-capable in your Ollama build |
| `qwen3-coder:30b` | Heavy coder role — unloads after use |

## Do not use for Friday “look”

A text-only GGUF (Saluki **without** mmproj, Unsloth text quants, etc.) has no vision projector. Screenshots → Ollama **500**.
