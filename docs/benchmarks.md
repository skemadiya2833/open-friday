# Benchmarks and evaluation

Friday includes timing helpers under `friday/bench/`. Results depend on your GPU, Ollama version, model quantizations, and Windows build. Treat numbers as **indicative**, not guarantees.

## Agent backends

| Harness | Command (help) | What it measures |
|---------|----------------|------------------|
| Legacy vision loop | `python -m friday.bench.run --backend legacy --help` | Screenshot → VLM → action tasks |
| Hybrid (UIA + vision) | `python -m friday.bench.run --backend hybrid --help` | Accessibility tree first, vision fallback |

**Caveats:** Do not touch mouse/keyboard during a live bench. Hybrid requires the Windows-MCP server enabled and `uv` available. Pass rates vary widely by task group (Notepad/Calculator vs Chrome canvas). Emergency-stop (Ctrl+Alt+F12) aborts runs.

## Other local benches

One-off latency / STT / routing probes used to live under `scripts/bench_*.py`. Those stay **local-only** (gitignored) so the public repo stays lean. Re-create them on your machine if you need a private harness.

For model-role and complexity routing behaviour, prefer the unit tests under `tests/test_complexity_routing.py` and `tests/test_agent_backend.py`. CI runs `pytest` + ruff — that is the correctness gate, not a perf scoreboard.

## Model defaults

Default local stack targets **16 GB VRAM** class GPUs with `qwen3.5:9b` as the unified model; vision-heavy tasks may use `qwen3-vl:8b-instruct` or `qwen2.5vl:7b-q4_K_M` when installed in Ollama. See `README.md` for recommended tags — Friday does not download models for you.

## Voice quality

Subjective TTS/STT quality requires listening on your microphone and speakers. `docs/VOICE_SAMPLES.md` describes how to capture samples locally under `data/voice_lab/` (gitignored).
