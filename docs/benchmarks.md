# Benchmarks and evaluation

Friday includes local benchmark harnesses under `friday/bench/` and `scripts/bench_*.py`. Results depend on your GPU, Ollama version, model quantizations, and Windows build. Treat numbers as **indicative**, not guarantees.

## Agent backends

| Harness | Command (help) | What it measures |
|---------|----------------|------------------|
| Legacy vision loop | `python -m friday.bench.run --backend legacy --help` | Screenshot → VLM → action tasks |
| Hybrid (UIA + vision) | `python -m friday.bench.run --backend hybrid --help` | Accessibility tree first, vision fallback |

**Caveats:** Do not touch mouse/keyboard during a live bench. Hybrid requires the Windows-MCP server enabled and `uv` available. Pass rates vary widely by task group (Notepad/Calculator vs Chrome canvas). Emergency-stop (Ctrl+Alt+F12) aborts runs.

## Other local benches (optional)

| Script | Purpose |
|--------|---------|
| `scripts/bench_fast_brain.py` | Latency of small “fast brain” routing |
| `scripts/bench_model_roles.py` | Role map vs single-model baseline |
| `scripts/bench_stt.py` / `bench_stt_real.py` | Speech-to-text plumbing |
| `scripts/bench_research_reports.py` | Research report pipeline |
| `scripts/bench_complexity_routing.py` | Complexity-based model routing (opt-in flag) |

Raw JSON outputs from development runs are kept out of the public repository. Re-run the scripts locally to reproduce curves on your hardware.

## Model defaults

Default local stack targets **16 GB VRAM** class GPUs with `qwen3.5:9b` as the unified model; vision-heavy tasks may use `qwen3-vl:8b-instruct` or `qwen2.5vl:7b-q4_K_M` when installed in Ollama. See `README.md` for recommended tags — Friday does not download models for you.

## Voice quality

Subjective TTS/STT quality requires listening on your microphone and speakers. `docs/VOICE_SAMPLES.md` describes how to capture samples locally under `data/voice_lab/` (gitignored).
