"""Streaming speech output with stop (for barge-in). Engines:

* ``kokoro`` / ``piper`` - LOCAL, run in an isolated worker process (``tts_worker.py``).
* ``edge``              - CLOUD (Microsoft Edge online voices). Text leaves the machine. Opt-in only.

``Speaker.say(text)`` returns immediately with a handle; audio is produced by a background thread and
written to a sink chunk by chunk, so the first audio plays after the first sentence is synthesised.
"""

from __future__ import annotations

import json
import os
import struct
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator, Protocol

import numpy as np

ROOT = Path(__file__).resolve().parents[2]


def default_worker_python() -> Path:
    env = os.getenv("FRIDAY_TTS_PYTHON")
    return Path(env) if env else ROOT / "data" / "voice_lab" / "tts" / "Scripts" / "python.exe"


class Sink(Protocol):
    def write(self, pcm: np.ndarray, sr: int) -> None: ...
    def stop(self) -> None: ...


class SoundDeviceSink:
    """Plays int16 mono PCM through the default output device."""

    def __init__(self) -> None:
        self._stream = None
        self._sr = 0
        self._lock = threading.Lock()

    def write(self, pcm: np.ndarray, sr: int) -> None:
        import sounddevice as sd

        with self._lock:
            if self._stream is None or sr != self._sr:
                if self._stream is not None:
                    self._stream.close()
                self._stream = sd.OutputStream(samplerate=sr, channels=1, dtype="int16")
                self._stream.start()
                self._sr = sr
            s = self._stream
        s.write(pcm.reshape(-1, 1))

    def stop(self) -> None:
        with self._lock:
            s, self._stream = self._stream, None
        if s is not None:
            try:
                s.abort()
                s.close()
            except Exception:  # noqa: BLE001
                pass


class NullSink:
    """Collects audio (used by tests and by the latency benchmark, which must not make noise)."""

    def __init__(self) -> None:
        self.chunks: list[np.ndarray] = []
        self.sr = 0
        self.stopped = False

    def write(self, pcm: np.ndarray, sr: int) -> None:
        self.chunks.append(pcm)
        self.sr = sr

    def stop(self) -> None:
        self.stopped = True


class WorkerEngine:
    """Local engine in an isolated interpreter. One request at a time."""

    def __init__(self, engine: str, voice: str | None = None, python: Path | None = None) -> None:
        self.engine, self.voice = engine, voice
        self.python = Path(python) if python else default_worker_python()
        self._p: subprocess.Popen | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        if self._p and self._p.poll() is None:
            return
        if not self.python.is_file():
            raise FileNotFoundError(f"TTS worker interpreter not found: {self.python} (see docs/research/voice.md)")
        env = {k: v for k, v in os.environ.items() if k in ("PATH", "SystemRoot", "TEMP", "TMP", "USERPROFILE", "LOCALAPPDATA")}
        self._p = subprocess.Popen([str(self.python), str(Path(__file__).with_name("tts_worker.py"))], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env)
        ready = json.loads(self._p.stdout.readline() or b"{}")
        if not ready.get("ready"):
            raise RuntimeError("TTS worker did not start")

    def stop(self) -> None:
        p, self._p = self._p, None
        if p and p.poll() is None:
            p.kill()

    def synth(self, text: str, cancelled: Callable[[], bool] = lambda: False) -> Iterator[tuple[np.ndarray, int]]:
        with self._lock:
            self.start()
            p = self._p
            assert p and p.stdin and p.stdout
            req = {"engine": self.engine, "text": text}
            if self.voice:
                req["voice"] = self.voice
            p.stdin.write((json.dumps(req) + "\n").encode())
            p.stdin.flush()
            head = json.loads(p.stdout.readline() or b"{}")
            if head.get("error"):
                p.stdout.read(4)
                raise RuntimeError(head["error"])
            sr = int(head.get("sr", 0))
            while True:
                n = struct.unpack("<I", p.stdout.read(4) or b"\0\0\0\0")[0]
                if n == 0:
                    return
                data = p.stdout.read(n)
                if cancelled():
                    # drain the rest so the worker stays in sync
                    while struct.unpack("<I", p.stdout.read(4) or b"\0\0\0\0")[0]:
                        pass
                    return
                yield np.frombuffer(data, dtype="<i2"), sr


class EdgeEngine:
    """CLOUD voice. Sends the text to Microsoft's online service. Disabled unless explicitly chosen."""

    LABEL = "cloud: text is sent to Microsoft"

    def __init__(self, voice: str = "en-IE-EmilyNeural") -> None:
        self.voice = voice

    def synth(self, text: str, cancelled: Callable[[], bool] = lambda: False) -> Iterator[tuple[np.ndarray, int]]:
        import asyncio
        import tempfile

        import edge_tts

        with tempfile.TemporaryDirectory() as d:
            mp3 = Path(d) / "o.mp3"
            asyncio.run(edge_tts.Communicate(text, self.voice).save(str(mp3)))
            import av

            c = av.open(str(mp3))
            rs = av.audio.resampler.AudioResampler(format="s16", layout="mono", rate=24000)
            for f in c.decode(audio=0):
                for o in rs.resample(f):
                    if cancelled():
                        return
                    yield o.to_ndarray().reshape(-1).astype(np.int16), 24000
            c.close()


@dataclass
class SpeakHandle:
    started: float = field(default_factory=time.perf_counter)
    first_audio_t: float | None = None
    done: threading.Event = field(default_factory=threading.Event)
    stopped: bool = False
    error: str = ""

    @property
    def first_audio_latency(self) -> float | None:
        return None if self.first_audio_t is None else self.first_audio_t - self.started


class Speaker:
    def __init__(self, engine, sink: Sink | None = None) -> None:
        self.engine, self.sink = engine, sink or SoundDeviceSink()
        self._h: SpeakHandle | None = None

    @property
    def speaking(self) -> bool:
        return self._h is not None and not self._h.done.is_set()

    def say(self, text: str) -> SpeakHandle:
        self.stop()
        h = SpeakHandle()
        self._h = h

        def run() -> None:
            try:
                for pcm, sr in self.engine.synth(text, cancelled=lambda: h.stopped):
                    if h.stopped:
                        break
                    if h.first_audio_t is None:
                        h.first_audio_t = time.perf_counter()
                    self.sink.write(pcm, sr)
            except Exception as exc:  # noqa: BLE001
                h.error = f"{type(exc).__name__}: {exc}"
            finally:
                h.done.set()

        threading.Thread(target=run, daemon=True, name="speaker").start()
        return h

    def stop(self) -> None:
        h = self._h
        if h is not None and not h.done.is_set():
            h.stopped = True
            self.sink.stop()
            h.done.wait(2.0)
