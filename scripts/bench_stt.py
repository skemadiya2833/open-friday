"""Measure faster-whisper speed/accuracy on CPU vs GPU for this machine.

Generates a local speech sample with SAPI (pyttsx3, no network), transcribes it with
each (model, device, compute_type) combination, and records load time, decode time,
real-time factor and word error rate against the known reference text.

Usage:
    python scripts/bench_stt.py --models base small large-v3-turbo --out docs/research/stt_bench.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time
import wave
from pathlib import Path

import numpy as np

os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

REFERENCE = (
    "Open the calendar and add a meeting with Sunil tomorrow at three thirty in the afternoon. "
    "Then remind me to charge the headset and turn the living room lights to warm white."
)


def make_sample(path: Path) -> float:
    import pyttsx3

    engine = pyttsx3.init()
    engine.setProperty("rate", 170)
    engine.save_to_file(REFERENCE, str(path))
    engine.runAndWait()
    with wave.open(str(path), "rb") as wf:
        return wf.getnframes() / float(wf.getframerate())


def load_wav_16k(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as wf:
        sr, ch, width = wf.getframerate(), wf.getnchannels(), wf.getsampwidth()
        raw = wf.readframes(wf.getnframes())
    if width != 2:
        raise RuntimeError(f"unexpected sample width {width}")
    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        audio = audio.reshape(-1, ch).mean(axis=1)
    if sr != 16000:
        n = int(len(audio) * 16000 / sr)
        audio = np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio).astype(np.float32)
    return audio


def wer(ref: str, hyp: str) -> float:
    norm = lambda s: re.sub(r"[^a-z0-9 ]", "", s.lower()).split()  # noqa: E731
    r, h = norm(ref), norm(hyp)
    d = [[0] * (len(h) + 1) for _ in range(len(r) + 1)]
    for i in range(len(r) + 1):
        d[i][0] = i
    for j in range(len(h) + 1):
        d[0][j] = j
    for i in range(1, len(r) + 1):
        for j in range(1, len(h) + 1):
            cost = 0 if r[i - 1] == h[j - 1] else 1
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost)
    return d[-1][-1] / max(1, len(r))


def run_case(model: str, device: str, compute: str, audio: np.ndarray, dur: float, repeats: int) -> dict:
    from faster_whisper import WhisperModel

    case = {"model": model, "device": device, "compute_type": compute}
    try:
        t0 = time.perf_counter()
        m = WhisperModel(model, device=device, compute_type=compute)
        case["load_s"] = round(time.perf_counter() - t0, 2)
        # warm-up (CUDA kernels / allocator)
        list(m.transcribe(audio, language="en", beam_size=1)[0])
        times, text = [], ""
        for _ in range(repeats):
            t0 = time.perf_counter()
            segs, _ = m.transcribe(audio, language="en", beam_size=1)
            text = " ".join(s.text.strip() for s in segs).strip()
            times.append(time.perf_counter() - t0)
        best = min(times)
        case.update(
            decode_s=round(best, 3),
            rtf=round(best / dur, 3),
            wer=round(wer(REFERENCE, text), 3),
            text=text,
        )
    except Exception as exc:  # noqa: BLE001
        case["error"] = f"{type(exc).__name__}: {exc}"[:300]
    return case


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", default=["base", "small"])
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--out", default="docs/research/stt_bench.json")
    ns = ap.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "sample.wav"
        dur = make_sample(wav)
        audio = load_wav_16k(wav)
    print(f"sample: {dur:.1f}s of local SAPI speech")

    results = []
    for model in ns.models:
        for device, compute in (("cpu", "int8"), ("cuda", "float16"), ("cuda", "int8_float16")):
            r = run_case(model, device, compute, audio, dur, ns.repeats)
            results.append(r)
            print(json.dumps({k: v for k, v in r.items() if k != "text"}))
    out = Path(ns.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"sample_seconds": dur, "reference": REFERENCE, "results": results}, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
