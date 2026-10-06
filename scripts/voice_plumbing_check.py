"""Plumbing checks for wake word + VAD + endpointing on synthetic speech clips (CPU only).

Run with any interpreter that has numpy, onnxruntime, openwakeword:
    python scripts/voice_plumbing_check.py

Loads friday.voice.{vad,wake} without importing friday/__init__ or friday.voice/__init__ (so it does
not need the full app environment).  Output: docs/research/voice_plumbing.json
"""

from __future__ import annotations

import json
import sys
import time
import types
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
for name, sub in (("friday", ""), ("friday.voice", "voice")):
    m = types.ModuleType(name)
    m.__path__ = [str(ROOT / "friday" / sub) if sub else str(ROOT / "friday")]
    sys.modules[name] = m

from friday.voice import vad as V   # noqa: E402
from friday.voice import wake as W  # noqa: E402

CLIPS = ROOT / "data" / "voice_lab" / "clips"


def load(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)


def main() -> int:
    manifest = json.loads((CLIPS / "manifest.json").read_text())
    res: dict = {"note": "SYNTHETIC speech (Windows SAPI David). Not a measure of accuracy on the owner's voice.", "clips": []}

    # ---- wake word
    ww = W.WakeWord()
    res["wake_model"], res["wake_threshold"] = ww.model_name, ww.threshold
    silence = np.zeros(16000, dtype=np.int16)
    for c in manifest:
        ww.reset()
        a = np.concatenate([silence, load(CLIPS / f"{c['id']}.wav"), silence])
        t0 = time.perf_counter()
        scores = [s for _, s in ww.scan(a)]
        dt = time.perf_counter() - t0
        res["clips"].append({"id": c["id"], "text": c["text"], "max_wake_score": round(max(scores), 3),
                             "fired": max(scores) >= ww.threshold, "ms_per_80ms_frame": round(dt / max(1, len(scores)) * 1000, 2)})
    # background noise: should not fire
    rng = np.random.default_rng(0)
    noise = (rng.normal(0, 800, 16000 * 10)).astype(np.int16)
    ww.reset()
    res["noise_max_wake_score"] = round(max(s for _, s in ww.scan(noise)), 3)

    # ---- VAD + endpointing
    vad = V.SileroVad(ROOT / "data" / "voice_lab" / "models" / "silero_vad.onnx")
    ep = V.Endpointer(vad)
    seq, truth = [], []
    for c in manifest[1:6]:
        seq += [silence[:12000], load(CLIPS / f"{c['id']}.wav"), silence[:16000]]
    audio = np.concatenate(seq).astype(np.float32) / 32768.0
    found, t0, n = [], time.perf_counter(), 0
    for i in range(0, len(audio) - V.FRAME + 1, V.FRAME):
        n += 1
        u = ep.feed(audio[i:i + V.FRAME])
        if u is not None:
            found.append(round(len(u) / 16000, 2))
    dt = time.perf_counter() - t0
    res["endpointing"] = {"clips_in": 5, "utterances_out": len(found), "utterance_seconds": found,
                          "expected_seconds": [manifest[i]["seconds"] for i in range(1, 6)],
                          "vad_ms_per_32ms_frame": round(dt / n * 1000, 3)}
    noise_f = (noise[:16000 * 5].astype(np.float32) / 32768.0)
    ep.reset()
    res["endpointing"]["false_utterances_in_noise"] = sum(
        1 for i in range(0, len(noise_f) - V.FRAME + 1, V.FRAME) if ep.feed(noise_f[i:i + V.FRAME]) is not None)

    out = ROOT / "docs" / "research" / "voice_plumbing.json"
    out.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
