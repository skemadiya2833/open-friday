"""Voice loop logic with scripted audio and fake models (no mic, no GPU, no onnx)."""

from __future__ import annotations

import time

import numpy as np

from friday.voice.pipeline import VoiceConfig, VoicePipeline
from friday.voice.speaker import NullSink, Speaker
from friday.voice.vad import Endpointer, EndpointConfig

WAKE_MARK = 12345


class FakeVad:
    def reset(self):
        pass

    def prob(self, frame):
        return 1.0 if float(np.abs(frame).max()) > 0.1 else 0.0


class FakeWake:
    def detect(self, f):
        return bool((f == WAKE_MARK).any())

    def reset(self):
        pass


def speech(ms):
    return np.full(int(16 * ms), 8000, dtype=np.int16)


def silence(ms):
    return np.zeros(int(16 * ms), dtype=np.int16)


def wake_clip():
    return np.full(1280, WAKE_MARK, dtype=np.int16)


class SlowEngine:
    """Yields 20 chunks, 20 ms apart, so a barge-in has something to interrupt."""

    def synth(self, text, cancelled=lambda: False):
        for _ in range(20):
            if cancelled():
                return
            time.sleep(0.02)
            yield np.zeros(480, dtype=np.int16), 24000


def build(cfg=None, respond=None, on_partial=None, transcribe=None):
    sink = NullSink()
    spk = Speaker(SlowEngine(), sink)
    ep = Endpointer(FakeVad(), EndpointConfig(min_silence_ms=200, start_frames=2, min_utterance_ms=100, pre_roll_ms=64))
    p = VoicePipeline(wake=FakeWake(), endpointer=ep, transcribe=transcribe or (lambda a: "open notepad"),
                      respond=respond or (lambda t: f"ok: {t}"), speaker=spk, cfg=cfg or VoiceConfig(listen_timeout_s=0.5),
                      on_partial=on_partial)
    return p, spk, sink


def wait(cond, t=3.0):
    end = time.time() + t
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_speech_without_wake_word_is_ignored():
    p, *_ = build()
    p.feed(np.concatenate([silence(200), speech(800), silence(600)]))
    time.sleep(0.2)
    assert p.turns == [] and p.state == "idle"


def test_full_turn_and_latency_breakdown():
    p, spk, sink = build()
    p.feed(np.concatenate([wake_clip(), silence(100), speech(700), silence(500)]))
    assert wait(lambda: p.turns)
    t = p.turns[0]
    assert t.text == "open notepad" and t.reply == "ok: open notepad" and not t.interrupted
    lat = t.latencies_ms()
    assert all(v is not None for v in lat.values()), lat
    assert lat["end_of_speech_to_first_audio"] >= lat["tts_first_audio"] >= 0
    assert sink.chunks and p.state == "idle"


def test_wake_word_barge_in_stops_speech_and_relistens():
    p, spk, sink = build()
    p.feed(np.concatenate([wake_clip(), speech(500), silence(500)]))
    assert wait(lambda: p.state == "speaking")
    p.feed(wake_clip())
    assert wait(lambda: sink.stopped)
    assert p.state == "listen"
    assert wait(lambda: p._cur is None or p._cur.interrupted or True)
    p.feed(np.concatenate([speech(500), silence(500)]))      # the user's next command
    assert wait(lambda: len(p.turns) >= 2, 5.0)
    assert any(t.interrupted for t in p.turns)


def test_plain_speech_does_not_interrupt_in_wake_mode():
    """No echo cancellation: speaker output leaking into the mic must not stop Friday."""
    p, spk, sink = build()
    p.feed(np.concatenate([wake_clip(), speech(500), silence(500)]))
    assert wait(lambda: p.state == "speaking")
    p.feed(speech(600))
    time.sleep(0.1)
    assert not sink.stopped


def test_vad_barge_in_mode():
    p, spk, sink = build(VoiceConfig(barge_in="vad", barge_in_ms=128, listen_timeout_s=0.5))
    p.feed(np.concatenate([wake_clip(), speech(500), silence(500)]))
    assert wait(lambda: p.state == "speaking")
    p.feed(speech(400))
    assert wait(lambda: sink.stopped) and p.state == "listen"


def test_listen_timeout_returns_to_idle():
    p, *_ = build(VoiceConfig(listen_timeout_s=0.1))
    p.feed(wake_clip())
    assert p.state == "listen"
    time.sleep(0.15)
    p.feed(silence(200))
    assert p.state == "idle"


def test_empty_transcript_gives_no_reply():
    p, spk, sink = build(transcribe=lambda a: "  ")
    p.feed(np.concatenate([wake_clip(), speech(500), silence(500)]))
    assert wait(lambda: p.turns)
    assert p.turns[0].reply == "" and not sink.chunks


def test_streaming_partials():
    seen = []
    p, *_ = build(on_partial=seen.append, transcribe=lambda a: f"{len(a)}")
    p.cfg.partial_every_s = 0.0
    p.feed(np.concatenate([wake_clip(), speech(1500)]))
    assert wait(lambda: seen)


def test_no_wake_mode_listens_immediately():
    p, *_ = build(VoiceConfig(wake_required=False, listen_timeout_s=5))
    p.feed(np.concatenate([speech(500), silence(500)]))
    assert wait(lambda: p.turns)


def test_responder_error_does_not_kill_the_loop():
    def boom(_):
        raise RuntimeError("llm down")

    p, *_ = build(respond=boom)
    p.feed(np.concatenate([wake_clip(), speech(500), silence(500)]))
    assert wait(lambda: p.turns)
    assert "llm down" in p.turns[0].reply and p.state == "idle"
