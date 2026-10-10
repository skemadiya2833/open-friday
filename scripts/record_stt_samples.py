"""Record YOUR voice saying 12 realistic Friday commands, for the STT accuracy benchmark.

    python scripts/record_stt_samples.py              # record all 12 (press Enter, speak, it stops on silence)
    python scripts/record_stt_samples.py --redo 5     # redo one
    python scripts/record_stt_samples.py --list       # show the prompts

Audio never leaves the machine: it is saved as 16 kHz mono WAV under data/voice_lab/real/ (git-ignored)
with data/voice_lab/real/manifest.json holding the reference text. Then run:

    python scripts/bench_stt_real.py --models large-v3-turbo small base

Tips: normal speaking pace, your normal mic position, a little room noise is fine. Read the sentence
as written (digits are spoken as words in the reference on purpose, see bench_stt_real.py).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "voice_lab" / "real"

PROMPTS = [
    "open notepad and type hello world",
    "what is the weather like today",
    "set a timer for ten minutes",
    "take a screenshot and tell me what you see",
    "turn the volume down to thirty percent",
    "open the calculator and compute twelve times fourteen",
    "search the web for the best local speech recognition models",
    "what is on my schedule tomorrow afternoon",
    "save this file as report dot text in the documents folder",
    "switch to the browser and open the first link",
    "remind me to call Priya at five thirty",
    "stop what you are doing",
]
SR = 16000


def record_until_silence(max_s: float = 12.0, silence_s: float = 1.0, thresh: float = 0.015) -> np.ndarray:
    import sounddevice as sd

    chunks: list[np.ndarray] = []
    heard, quiet_since, t0 = False, None, time.time()
    with sd.InputStream(samplerate=SR, channels=1, dtype="float32", blocksize=1600) as s:
        while time.time() - t0 < max_s:
            data, _ = s.read(1600)
            x = data[:, 0].copy()
            chunks.append(x)
            loud = float(np.sqrt(np.mean(x ** 2))) > thresh
            if loud:
                heard, quiet_since = True, None
            elif heard:
                quiet_since = quiet_since or time.time()
                if time.time() - quiet_since >= silence_s:
                    break
    return np.concatenate(chunks)


def write_wav(path: Path, audio: np.ndarray) -> None:
    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--redo", type=int, help="1-based index of one prompt to re-record")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.list:
        for i, p in enumerate(PROMPTS, 1):
            print(f"{i:2d}. {p}")
        return 0
    OUT.mkdir(parents=True, exist_ok=True)
    mf = OUT / "manifest.json"
    manifest = {m["id"]: m for m in json.loads(mf.read_text())} if mf.exists() else {}
    todo = [a.redo] if a.redo else range(1, len(PROMPTS) + 1)
    for i in todo:
        text = PROMPTS[i - 1]
        while True:
            input(f"\n[{i}/{len(PROMPTS)}] Press Enter, then say:\n    \"{text}\"\n> ")
            audio = record_until_silence()
            secs = len(audio) / SR
            peak = float(np.abs(audio).max())
            print(f"  recorded {secs:.1f}s, peak {peak:.2f}")
            if peak < 0.02:
                print("  too quiet (is the right microphone selected?). Try again.")
                continue
            if input("  keep it? [Y/n] ").strip().lower() in ("", "y", "yes"):
                break
        cid = f"r{i:02d}"
        write_wav(OUT / f"{cid}.wav", audio)
        manifest[cid] = {"id": cid, "text": text, "seconds": round(secs, 2), "peak": round(peak, 3)}
        mf.write_text(json.dumps(list(manifest.values()), indent=1), encoding="utf-8")
    print(f"\nDone. {len(manifest)} recordings in {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
