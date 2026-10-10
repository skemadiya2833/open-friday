"""Local TTS evaluation: Kokoro (Apache-2.0 model, kokoro-onnx) vs Piper (GPL, separate process) vs Windows SAPI.
Optional: --cloud adds edge-tts (CLOUD: sends text to Microsoft).

Measures per engine: worker start + model load, first-audio latency (cold and warm), real-time factor.
Writes WAV samples to data/voice_lab/tts_samples/ so the owner can LISTEN (quality is subjective and is
NOT scored here: UNVERIFIED until a human listens) and docs/research/tts_eval.json.
Never opens an audio device. Run with the main interpreter:  python scripts/tts_eval.py
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from friday.voice.speaker import EdgeEngine, NullSink, Speaker, WorkerEngine  # noqa: E402

SENTENCES = [
    "Okay, I opened Notepad and typed hello world.",
    "I could not find the Save button, so I am trying the keyboard shortcut instead. If that does not work I will ask you what to do next.",
    "You have three meetings tomorrow. The first one starts at nine thirty.",
]
OUT = ROOT / "data" / "voice_lab" / "tts_samples"


def save(path: Path, chunks, sr) -> float:
    pcm = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(sr or 24000)
        w.writeframes(pcm.astype("<i2").tobytes())
    return len(pcm) / float(sr or 24000)


def eval_engine(name: str, engine) -> dict:
    res: dict = {"engine": name, "runs": []}
    for i, text in enumerate(SENTENCES):
        sink = NullSink()
        spk = Speaker(engine, sink)
        t0 = time.perf_counter()
        h = spk.say(text)
        h.done.wait(120)
        wall = time.perf_counter() - t0
        if h.error:
            res["error"] = h.error
            break
        secs = save(OUT / f"{name}_{i + 1}.wav", sink.chunks, sink.sr)
        res["runs"].append({"sentence": i + 1, "chars": len(text), "first_audio_ms": round((h.first_audio_latency or 0) * 1000),
                            "total_synth_s": round(wall, 2), "audio_s": round(secs, 2), "rtf": round(wall / secs, 3) if secs else None,
                            "cold": i == 0})
    return res


def sapi(text: str, dest: Path) -> float:
    ps = ("Add-Type -AssemblyName System.Speech; $s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
          "$s.SetOutputToWaveFile($env:D); $s.Speak($env:T); $s.Dispose()")
    t0 = time.perf_counter()
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], env={**os.environ, "D": str(dest), "T": text}, check=True, timeout=60)
    return time.perf_counter() - t0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cloud", action="store_true", help="also test edge-tts (sends text to Microsoft)")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    report: dict = {"note": "first_audio_ms for local engines = time to first synthesised sentence chunk; quality not scored",
                    "engines": []}
    for name, eng in (("kokoro", WorkerEngine("kokoro", "af_heart")), ("piper", WorkerEngine("piper", "en_US-lessac-medium"))):
        t0 = time.perf_counter()
        try:
            eng.start()
            start_s = time.perf_counter() - t0
            r = eval_engine(name, eng)
            r["worker_start_s"] = round(start_s, 2)
            r["license"] = {"kokoro": "kokoro-onnx MIT + Kokoro-82M weights Apache-2.0", "piper": "piper-tts GPL-3.0 (separate process only)"}[name]
        except Exception as exc:  # noqa: BLE001
            r = {"engine": name, "error": f"{type(exc).__name__}: {exc}"}
        finally:
            eng.stop()
        report["engines"].append(r)
        print(json.dumps(r))
    runs = []
    for i, text in enumerate(SENTENCES):
        wall = sapi(text, OUT / f"sapi_{i + 1}.wav")
        with wave.open(str(OUT / f"sapi_{i + 1}.wav"), "rb") as w:
            secs = w.getnframes() / w.getframerate()
        runs.append({"sentence": i + 1, "first_audio_ms": round(wall * 1000), "audio_s": round(secs, 2), "rtf": round(wall / secs, 3),
                     "note": "file render: first audio = whole utterance"})
    report["engines"].append({"engine": "windows-sapi", "runs": runs, "license": "OS component, offline"})
    if a.cloud:
        r = eval_engine("edge", EdgeEngine())
        r["label"] = EdgeEngine.LABEL
        report["engines"].append(r)
    (ROOT / "docs" / "research" / "tts_eval.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
