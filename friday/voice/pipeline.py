"""Hands-free voice loop: wake word -> VAD endpointing -> STT -> reply -> speech, with barge-in.

All heavy parts are injected so the loop is testable with scripted audio:
    wake(frame_i16[1280]) -> bool            openWakeWord
    endpointer.feed(frame_f32[512]) -> utterance | None     Silero VAD
    transcribe(audio_f32) -> str             faster-whisper
    respond(text) -> str                     the chat/agent path
    speaker.say(text) / .stop() / .speaking  streaming TTS

Barge-in while Friday is speaking:
    mode "wake"  (default, safe with speakers): only the wake word interrupts, because the mic hears the
                 speaker and plain VAD would make Friday interrupt itself (there is no echo cancellation).
    mode "vad"   (headphones): sustained speech interrupts.
Every turn records timestamps so end-to-end latency can be measured.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable

import numpy as np

SR = 16000
WAKE_FRAME = 1280
VAD_FRAME = 512


class Rechunker:
    def __init__(self, n: int, dtype) -> None:
        self.n, self._buf = n, np.zeros(0, dtype=dtype)

    def push(self, x: np.ndarray):
        self._buf = np.concatenate([self._buf, x.astype(self._buf.dtype, copy=False)])
        while len(self._buf) >= self.n:
            out, self._buf = self._buf[: self.n], self._buf[self.n:]
            yield out


@dataclass
class Turn:
    text: str = ""
    reply: str = ""
    t_speech_end: float | None = None      # clock of the last speech frame
    t_endpoint: float | None = None        # endpointer released the utterance
    t_text: float | None = None            # transcript ready
    t_reply: float | None = None           # reply text ready
    t_first_audio: float | None = None
    interrupted: bool = False

    def latencies_ms(self) -> dict[str, float | None]:
        def d(a, b):
            return None if a is None or b is None else round((b - a) * 1000, 1)
        return {"endpoint_wait": d(self.t_speech_end, self.t_endpoint), "stt": d(self.t_endpoint, self.t_text),
                "reply": d(self.t_text, self.t_reply), "tts_first_audio": d(self.t_reply, self.t_first_audio),
                "end_of_speech_to_first_audio": d(self.t_speech_end, self.t_first_audio)}


@dataclass
class VoiceConfig:
    wake_required: bool = True
    barge_in: str = "wake"            # "wake" | "vad" | "off"
    barge_in_ms: int = 250
    listen_timeout_s: float = 6.0
    partial_every_s: float = 1.0      # streaming STT: re-decode the growing utterance this often


class VoicePipeline:
    def __init__(self, *, wake, endpointer, transcribe: Callable[[np.ndarray], str],
                 respond: Callable[[str], str], speaker, cfg: VoiceConfig | None = None,
                 clock: Callable[[], float] = time.perf_counter,
                 on_turn: Callable[[Turn], None] | None = None,
                 on_partial: Callable[[str], None] | None = None) -> None:
        self.wake, self.ep, self.transcribe, self.respond, self.speaker = wake, endpointer, transcribe, respond, speaker
        self.cfg, self.clock, self.on_turn, self.on_partial = cfg or VoiceConfig(), clock, on_turn, on_partial
        self._last_partial = 0.0
        self._partial_busy = False
        self.state = "idle" if self.cfg.wake_required else "listen"
        self.turns: list[Turn] = []
        self._rw, self._rv = Rechunker(WAKE_FRAME, np.int16), Rechunker(VAD_FRAME, np.float32)
        self._listen_since = self.clock()
        self._speech_ms = 0.0
        self._work: threading.Thread | None = None
        self._cur: Turn | None = None
        self._lock = threading.Lock()

    # ----------------------------------------------------------------- audio in
    def feed(self, pcm_i16: np.ndarray) -> None:
        """Feed any amount of 16 kHz mono int16 audio (from the mic or a file)."""
        for w in self._rw.push(pcm_i16):
            skip_vad = False
            if self.state == "idle" and self.wake.detect(w):
                self._to_listen()
                skip_vad = True          # the chunk that carried the wake word is not part of the command
            elif self.state == "speaking" and self.cfg.barge_in == "wake" and self.wake.detect(w):
                self._barge_in()
                skip_vad = True
            if skip_vad:
                self._rv = Rechunker(VAD_FRAME, np.float32)
                continue
            for f in self._rv.push(w.astype(np.float32) / 32768.0):
                self._on_vad_frame(f)

    def _to_listen(self) -> None:
        self.ep.reset()
        self.state, self._listen_since = "listen", self.clock()
        try:
            self.wake.reset()
        except Exception:  # noqa: BLE001
            pass

    def _barge_in(self) -> None:
        cur = self._cur
        if cur is not None:
            cur.interrupted = True        # before stop(): the turn thread finishes as soon as audio stops
        self.speaker.stop()
        self._to_listen()

    def _on_vad_frame(self, f: np.ndarray) -> None:
        if self.state == "listen":
            u = self.ep.feed(f, now=self.clock())
            if u is not None:
                with self._lock:
                    self.state = "busy"
                turn = Turn(t_speech_end=self.ep.speech_end_t, t_endpoint=self.clock())
                self._work = threading.Thread(target=self._handle, args=(u, turn), daemon=True)
                self._work.start()
            elif self.ep.speaking and self.on_partial and not self._partial_busy \
                    and self.clock() - self._last_partial >= self.cfg.partial_every_s:
                self._last_partial = self.clock()
                self._partial_busy = True
                threading.Thread(target=self._partial, args=(self.ep.buffered(),), daemon=True).start()
            elif not self.ep.speaking and self.clock() - self._listen_since > self.cfg.listen_timeout_s:
                self.state = "idle" if self.cfg.wake_required else "listen"
                self._listen_since = self.clock()
        elif self.state == "speaking" and self.cfg.barge_in == "vad":
            p = self.ep.vad.prob(f)
            self._speech_ms = self._speech_ms + 32 if p > 0.6 else 0.0
            if self._speech_ms >= self.cfg.barge_in_ms:
                self._speech_ms = 0.0
                self._barge_in()

    def _partial(self, audio: np.ndarray) -> None:
        try:
            if len(audio) > SR // 2:
                self.on_partial(self.transcribe(audio).strip())      # type: ignore[misc]
        except Exception:  # noqa: BLE001 - partials are best effort
            pass
        finally:
            self._partial_busy = False

    # ----------------------------------------------------------------- one turn
    def _handle(self, audio: np.ndarray, turn: Turn) -> None:
        try:
            turn.text = self.transcribe(audio).strip()
            turn.t_text = self.clock()
            if not turn.text:
                self._finish(turn, idle=True)
                return
            turn.reply = self.respond(turn.text)
            turn.t_reply = self.clock()
            self._cur = turn
            with self._lock:
                self.state = "speaking"
            h = self.speaker.say(turn.reply)
            while h.first_audio_t is None and not h.done.is_set():
                time.sleep(0.002)
            turn.t_first_audio = h.first_audio_t
            h.done.wait()
        except Exception as exc:  # noqa: BLE001
            turn.reply = f"[error: {type(exc).__name__}: {exc}]"
        self._finish(turn, idle=True)

    def _finish(self, turn: Turn, idle: bool) -> None:
        self.turns.append(turn)
        if self.on_turn:
            self.on_turn(turn)
        self._cur = None
        with self._lock:
            if self.state in ("busy", "speaking"):          # not already moved to listen by a barge-in
                self.state = "idle" if self.cfg.wake_required else "listen"
                self._listen_since = self.clock()

    def join(self, timeout: float = 30.0) -> None:
        if self._work is not None:
            self._work.join(timeout)
