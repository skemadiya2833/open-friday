"""Standalone TTS worker. Runs in an ISOLATED interpreter (``data/voice_lab/tts``, Python 3.12).

Why isolated: kokoro-onnx needs Python <3.14, and piper-tts is GPL-3.0-or-later, so Friday never imports
it; it talks to this process over stdin/stdout only. This file imports nothing from ``friday``.

Protocol (stdin, one JSON object per line):
    {"engine": "kokoro"|"piper", "text": "...", "voice": "af_heart", "speed": 1.0}
Reply on stdout (binary):  line ``{"sr": 24000}\\n`` then repeated  <uint32 LE n><n bytes int16 PCM>,
terminated by n == 0.  Chunks are emitted as soon as each sentence is synthesised (streaming).
Start-up line: ``{"ready": true, "engines": [...]}``.
"""

from __future__ import annotations

import asyncio
import json
import os
import struct
import sys
import time
from pathlib import Path

import numpy as np

MODELS = Path(os.environ.get("FRIDAY_TTS_MODELS", Path(__file__).resolve().parents[2] / "data" / "voice_lab" / "models"))
_kokoro = None
_piper = {}


def _out(b: bytes) -> None:
    sys.stdout.buffer.write(b)
    sys.stdout.buffer.flush()


def _i16(x: np.ndarray) -> bytes:
    return (np.clip(x, -1, 1) * 32767).astype("<i2").tobytes()


def _get_kokoro():
    global _kokoro
    if _kokoro is None:
        from kokoro_onnx import Kokoro

        _kokoro = Kokoro(str(MODELS / "kokoro" / "kokoro-v1.0.onnx"), str(MODELS / "kokoro" / "voices-v1.0.bin"))
    return _kokoro


def _get_piper(voice: str):
    if voice not in _piper:
        from piper import PiperVoice

        _piper[voice] = PiperVoice.load(str(MODELS / "piper" / f"{voice}.onnx"))
    return _piper[voice]


async def _kokoro_stream(req) -> None:
    k = _get_kokoro()
    first = True
    async for samples, sr in k.create_stream(req["text"], voice=req.get("voice", "af_heart"), speed=float(req.get("speed", 1.0))):
        if first:
            _out((json.dumps({"sr": sr}) + "\n").encode())
            first = False
        b = _i16(samples)
        _out(struct.pack("<I", len(b)) + b)


def _piper_stream(req) -> None:
    v = _get_piper(req.get("voice", "en_US-lessac-medium"))
    first = True
    for chunk in v.synthesize(req["text"]):
        if first:
            _out((json.dumps({"sr": chunk.sample_rate}) + "\n").encode())
            first = False
        b = chunk.audio_int16_bytes
        _out(struct.pack("<I", len(b)) + b)


def main() -> int:
    _out((json.dumps({"ready": True, "engines": ["kokoro", "piper"]}) + "\n").encode())
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            if req.get("engine") == "kokoro":
                asyncio.run(_kokoro_stream(req))
            elif req.get("engine") == "piper":
                _piper_stream(req)
            else:
                raise ValueError("unknown engine")
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write(f"worker error: {type(exc).__name__}: {exc}\n")
            sys.stderr.flush()
            _out((json.dumps({"sr": 0, "error": str(exc)[:200]}) + "\n").encode())
        _out(struct.pack("<I", 0))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
