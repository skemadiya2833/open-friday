"""Render a fixed command list to 16 kHz mono WAV files with the local Windows SAPI voices.

Synthetic speech is NOT a substitute for the owner's voice: it is used for plumbing tests
(wake word, VAD, latency) and as a clearly labelled lower-bound sanity check for STT.
Output: data/voice_lab/clips/<id>.wav  (+ manifest.json with the reference text)
"""

from __future__ import annotations

import json
import sys
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

COMMANDS = [
    ("c01", "hey jarvis"),
    ("c02", "open notepad and type hello world"),
    ("c03", "what is the weather like today"),
    ("c04", "set a timer for ten minutes"),
    ("c05", "take a screenshot and tell me what you see"),
    ("c06", "turn the volume down"),
    ("c07", "open the calculator and compute twelve times fourteen"),
    ("c08", "search the web for local speech recognition models"),
    ("c09", "what is on my schedule tomorrow"),
    ("c10", "stop"),
]


def to_16k(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        sr, ch, sw = w.getframerate(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(w.getnframes())
    x = np.frombuffer(raw, dtype=np.int16 if sw == 2 else np.uint8).astype(np.float32)
    if sw == 1:
        x = (x - 128) * 256
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    if sr != 16000:
        n = int(len(x) * 16000 / sr)
        x = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x)
    return np.clip(x, -32768, 32767).astype(np.int16)


PS = r"""
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$v = $s.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -like 'en-*' } | Select-Object -First 1
if ($v) { $s.SelectVoice($v.VoiceInfo.Name) }
$s.Rate = 0
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
$s.SetOutputToWaveFile($env:SYN_DEST, $fmt)
$s.Speak($env:SYN_TEXT)
$s.Dispose()
Write-Output $v.VoiceInfo.Name
"""


def main() -> int:
    import os
    import subprocess

    out = ROOT / "data" / "voice_lab" / "clips"
    out.mkdir(parents=True, exist_ok=True)
    manifest = []
    for cid, text in COMMANDS:
        dest = out / f"{cid}.wav"
        r = subprocess.run(["powershell", "-NoProfile", "-Command", PS], env={**os.environ, "SYN_DEST": str(dest), "SYN_TEXT": text},
                           capture_output=True, text=True, timeout=60)
        if r.returncode != 0 or not dest.exists():
            print("FAILED", cid, r.stderr[:300])
            return 1
        pcm = to_16k(dest)
        manifest.append({"id": cid, "text": text, "seconds": round(len(pcm) / 16000, 2), "voice": r.stdout.strip()})
        print(cid, text, manifest[-1]["seconds"], "s", manifest[-1]["voice"])
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

