"""Text-to-speech pipeline for the HUD speak API.

Order (auto):
  1. Kokoro-82M local neural (af_heart female) — best offline quality
  2. Piper local neural (lessac female)
  3. Edge online (often 403 — cools down)
  4. Google gTTS
  5. Windows SAPI / browser

Kokoro/Piper run in ``data/voice_lab/tts`` (Python 3.12 worker) so the main
3.14 env never imports GPL piper or kokoro-onnx.
"""

from __future__ import annotations

import asyncio
import io
import re
import shutil
import subprocess
import tempfile
import threading
import time
import wave
from pathlib import Path

from friday.config import VOICE_TTS_VOICE
from friday.persona import DEFAULT_EDGE_VOICE

_EDGE_FALLBACKS = (
    "en-US-AvaNeural",
    "en-US-JennyNeural",
    "en-US-AriaNeural",
)

_KOKORO_VOICES = frozenset(
    {
        "af_heart",
        "af_bella",
        "af_nicole",
        "af_sarah",
        "af_sky",
        "af_alloy",
        "bf_emma",
        "bf_isabella",
        "bf_alice",
        "bf_lily",
    }
)
_DEFAULT_KOKORO_VOICE = "af_heart"
_DEFAULT_PIPER_VOICE = "en_US-lessac-medium"

# When Bing Edge TTS returns 403, skip Edge for a while (do not thrash voices).
_edge_cooldown_until = 0.0
_EDGE_COOLDOWN_S = 900.0
_EDGE_ATTEMPT_TIMEOUT_S = 6.0

_worker_engines: dict[str, object] = {}
_worker_lock = threading.Lock()


def _models_root() -> Path:
    from friday.config import DATA_DIR

    return Path(DATA_DIR) / "voice_lab" / "models"


def _kokoro_ready() -> bool:
    root = _models_root() / "kokoro"
    return (root / "kokoro-v1.0.onnx").is_file() and (root / "voices-v1.0.bin").is_file()


def _piper_ready(voice: str = _DEFAULT_PIPER_VOICE) -> bool:
    return (_models_root() / "piper" / f"{voice}.onnx").is_file()


def _resolve_edge_voice(configured: str) -> str:
    v = (configured or "").strip()
    if not v or v in _KOKORO_VOICES or "en_US" in v or v.endswith("-medium") or v.endswith(".onnx"):
        return DEFAULT_EDGE_VOICE
    if v.startswith("en-") and "Neural" in v:
        return v
    return DEFAULT_EDGE_VOICE


def _resolve_kokoro_voice(configured: str) -> str:
    v = (configured or "").strip()
    if v in _KOKORO_VOICES:
        return v
    return _DEFAULT_KOKORO_VOICE


def _tts_engine_pref() -> str:
    try:
        from friday.runtime.prefs import get as pref

        return str(pref("tts_engine") or "auto").strip().lower()
    except Exception:  # noqa: BLE001
        return "auto"


def _configured_voice() -> str:
    try:
        from friday.runtime.prefs import get as pref

        return str(pref("tts_voice") or VOICE_TTS_VOICE or "").strip()
    except Exception:  # noqa: BLE001
        return (VOICE_TTS_VOICE or "").strip()


def _normalize_rate(rate: str | None) -> str:
    r = (rate or "+0%").strip()
    if re.fullmatch(r"[+-]?\d{1,3}%", r):
        n = int(r.rstrip("%"))
        n = max(-50, min(50, n))
        return f"{n:+d}%"
    return "+0%"


def _speed_from_rate(rate: str | None) -> float:
    r = _normalize_rate(rate)
    try:
        n = int(r.rstrip("%"))
    except ValueError:
        n = 0
    return max(0.75, min(1.35, 1.0 + (n / 100.0)))


def _pcm16_to_wav(pcm: bytes, sr: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(sr) or 24000)
        w.writeframes(pcm)
    return buf.getvalue()


def _worker_synth_wav(engine: str, text: str, *, voice: str, speed: float = 1.0) -> bytes | None:
    """Synthesize via isolated voice_lab worker → WAV bytes."""
    try:
        from friday.voice.speaker import WorkerEngine, default_worker_python
    except Exception as exc:  # noqa: BLE001
        print(f"[TTS] worker import failed: {exc}")
        return None

    py = default_worker_python()
    if not py.is_file():
        print(f"[TTS] voice worker Python missing: {py}")
        return None

    key = f"{engine}:{voice}:{speed:.2f}"
    try:
        with _worker_lock:
            eng = _worker_engines.get(key)
            if eng is None:
                eng = WorkerEngine(engine, voice=voice, python=py, speed=speed)
                _worker_engines[key] = eng
            else:
                eng.speed = speed  # type: ignore[attr-defined]
            chunks: list[bytes] = []
            sr = 24000
            for pcm, rate in eng.synth(text):  # type: ignore[attr-defined]
                sr = int(rate) or sr
                chunks.append(pcm.tobytes() if hasattr(pcm, "tobytes") else bytes(pcm))
            if not chunks:
                return None
            return _pcm16_to_wav(b"".join(chunks), sr)
    except Exception as exc:  # noqa: BLE001
        print(f"[TTS] {engine}/{voice} failed: {exc}")
        # Drop broken engine so the next call can restart the worker.
        with _worker_lock:
            dead = _worker_engines.pop(key, None)
            if dead is not None:
                try:
                    dead.stop()  # type: ignore[attr-defined]
                except Exception:  # noqa: BLE001
                    pass
        return None


def _kokoro_bytes(text: str, rate: str | None = None, *, voice: str | None = None) -> bytes | None:
    if not _kokoro_ready():
        return None
    voice = _resolve_kokoro_voice(voice or _configured_voice())
    return _worker_synth_wav("kokoro", text, voice=voice, speed=_speed_from_rate(rate))


def _piper_neural_bytes(text: str) -> bytes | None:
    if not _piper_ready():
        return None
    return _worker_synth_wav("piper", text, voice=_DEFAULT_PIPER_VOICE, speed=1.0)


def _edge_voice_candidates(*, max_voices: int = 2, voice: str | None = None) -> list[str]:
    voice_name = (voice or "").strip() or VOICE_TTS_VOICE
    if not voice:
        try:
            from friday.runtime.prefs import get as pref

            voice_name = str(pref("tts_voice") or VOICE_TTS_VOICE)
        except Exception:  # noqa: BLE001
            pass
    primary = _resolve_edge_voice(voice_name)
    out = [primary]
    # Preview of a specific Edge voice: try only that name (no silent fallback swap).
    if voice and primary == _resolve_edge_voice(voice):
        return out[:1]
    for alt in _EDGE_FALLBACKS:
        if alt not in out:
            out.append(alt)
        if len(out) >= max_voices:
            break
    return out


async def _edge_bytes(text: str, voice: str, rate_s: str) -> bytes:
    import edge_tts

    communicate = edge_tts.Communicate(text, voice, rate=rate_s)
    chunks: list[bytes] = []
    async for part in communicate.stream():
        if part.get("type") == "audio" and part.get("data"):
            chunks.append(part["data"])
    return b"".join(chunks)


def _is_edge_auth_block(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "403" in msg or "invalid response status" in msg or "unauthorized" in msg or "timeout" in msg


def edge_available() -> bool:
    return time.monotonic() >= _edge_cooldown_until


def _edge_tts_bytes(
    text: str, rate: str | None = None, *, voice: str | None = None
) -> bytes | None:
    global _edge_cooldown_until

    try:
        import edge_tts  # noqa: F401
    except ImportError:
        return None

    if time.monotonic() < _edge_cooldown_until:
        return None

    rate_s = _normalize_rate(rate)
    # One primary + one alt max; abort the whole Edge path on auth failure.
    for cand in _edge_voice_candidates(max_voices=2 if not voice else 1, voice=voice):
        try:
            data = asyncio.run(
                asyncio.wait_for(_edge_bytes(text, cand, rate_s), timeout=_EDGE_ATTEMPT_TIMEOUT_S)
            )
            if data and len(data) > 44:
                return data
            raise RuntimeError("empty audio")
        except Exception as exc:  # noqa: BLE001
            print(f"[TTS] edge-tts {cand} failed: {exc}")
            if _is_edge_auth_block(exc):
                _edge_cooldown_until = time.monotonic() + _EDGE_COOLDOWN_S
                print(
                    f"[TTS] edge-tts unavailable — cool-down {_EDGE_COOLDOWN_S:.0f}s; "
                    "client should use browser voice"
                )
                return None
    return None


def _engine_for_preview(voice: str | None, engine: str | None) -> str:
    """Pick which synthesizer hears a Systems preview of ``voice``.

    Voice identity wins so selecting Ava plays Ava (Edge), not a Kokoro stand-in.
    """
    v = (voice or "").strip()
    if v in _KOKORO_VOICES or v.startswith(("af_", "bf_")):
        return "kokoro"
    if "Neural" in v or v.startswith("en-"):
        return "edge"
    if v.startswith("en_US") or v.endswith(("-medium", ".onnx")):
        return "piper"
    eng = (engine or "").strip().lower()
    if eng and eng != "auto":
        return eng
    return (_tts_engine_pref() or "auto").strip().lower() or "auto"


def _edge_tts(text: str, out: Path, rate: str | None = None) -> bool:
    data = _edge_tts_bytes(text, rate=rate)
    if not data:
        return False
    out.write_bytes(data)
    return out.exists() and out.stat().st_size > 44


def _gtts_bytes(text: str, *, timeout_s: float = 12.0) -> bytes | None:
    """Google Translate TTS — free, no API key, better than SAPI when Edge is down."""
    try:
        from gtts import gTTS  # type: ignore[import-untyped]
    except ImportError:
        return None

    result: dict[str, bytes | None] = {"data": None}

    def _worker() -> None:
        try:
            buf = io.BytesIO()
            # tld=com = standard US-ish Google voice; no Microsoft dependency.
            gTTS(text=text, lang="en", tld="com", slow=False).write_to_fp(buf)
            data = buf.getvalue()
            if data and len(data) > 100:
                result["data"] = data
        except Exception as exc:  # noqa: BLE001
            print(f"[TTS] gTTS failed: {exc}")

    th = threading.Thread(target=_worker, daemon=True, name="FridayGTTS")
    th.start()
    th.join(timeout=timeout_s)
    if th.is_alive():
        print(f"[TTS] gTTS timed out after {timeout_s:.0f}s")
        return None
    return result["data"]


def _gtts_tts(text: str, out: Path) -> bool:
    data = _gtts_bytes(text)
    if not data:
        return False
    mp3 = out if out.suffix.lower() == ".mp3" else out.with_suffix(".mp3")
    mp3.write_bytes(data)
    if mp3 != out and out.suffix.lower() != ".mp3":
        return mp3.exists() and mp3.stat().st_size > 100
    return mp3.exists() and mp3.stat().st_size > 100


def _piper_tts(text: str, out: Path) -> bool:
    piper = shutil.which("piper")
    if not piper:
        return False
    model = VOICE_TTS_VOICE
    if model.startswith("en-") and "Neural" in model:
        return False
    proc = subprocess.run(
        [piper, "--model", model, "--output_file", str(out)],
        input=text.encode("utf-8"),
        capture_output=True,
        timeout=60,
    )
    if proc.returncode == 0 and out.exists() and out.stat().st_size > 44:
        return True
    print(f"[TTS] Piper failed: {proc.stderr.decode(errors='ignore')[:200]}")
    return False


_pyttsx3_lock = threading.Lock()


def _pyttsx3_tts(text: str, out: Path, *, timeout_s: float = 12.0) -> bool:
    """Local SAPI — serialize (Windows hates two engines) + hard-timeout."""
    result: dict[str, bool] = {"ok": False}

    def _worker() -> None:
        try:
            import pyttsx3

            wav = out if out.suffix.lower() == ".wav" else out.with_suffix(".wav")
            with _pyttsx3_lock:
                engine = pyttsx3.init()
                try:
                    for voice in engine.getProperty("voices") or []:
                        name = f"{getattr(voice, 'name', '')} {getattr(voice, 'id', '')}".lower()
                        if any(k in name for k in ("zira", "female", "eva", "hazel", "susan")):
                            engine.setProperty("voice", voice.id)
                            break
                except Exception:
                    pass
                engine.setProperty("rate", 175)
                engine.save_to_file(text, str(wav.resolve()))
                engine.runAndWait()
                try:
                    engine.stop()
                except Exception:
                    pass
            if wav.exists() and wav.stat().st_size > 44:
                if wav != out:
                    wav.replace(out)
                result["ok"] = True
        except Exception as exc:  # noqa: BLE001
            print(f"[TTS] pyttsx3 fallback failed: {exc}")

    th = threading.Thread(target=_worker, daemon=True, name="FridayPyttsx3")
    th.start()
    th.join(timeout=timeout_s)
    if th.is_alive():
        print(f"[TTS] pyttsx3 timed out after {timeout_s:.0f}s — skipping")
        return False
    return bool(result["ok"])


def _scrub(text: str) -> str:
    clean = (text or "").strip()
    if not clean:
        return ""
    try:
        from friday.security.content_scan import scan_speech

        spoken = scan_speech(clean)
        if spoken.blocked:
            return "I can't say that out loud — it looked like a secret."
        return spoken.text.strip() or clean
    except Exception:  # noqa: BLE001
        return clean


def _synthesize_pipeline(
    clean: str,
    rate: str | None = None,
    *,
    voice: str | None = None,
    engine: str | None = None,
) -> tuple[bytes, str]:
    """Run the preferred engine chain. Returns (bytes, mime) or empty text/plain."""
    engine = _engine_for_preview(voice, engine) if (voice or engine) else _tts_engine_pref()
    voice_ov = (voice or "").strip() or None

    def try_kokoro() -> tuple[bytes, str] | None:
        data = _kokoro_bytes(clean, rate=rate, voice=voice_ov)
        return (data, "audio/wav") if data else None

    def try_piper() -> tuple[bytes, str] | None:
        data = _piper_neural_bytes(clean)
        return (data, "audio/wav") if data else None

    def try_edge() -> tuple[bytes, str] | None:
        data = _edge_tts_bytes(clean, rate=rate, voice=voice_ov)
        return (data, "audio/mpeg") if data else None

    def try_gtts() -> tuple[bytes, str] | None:
        data = _gtts_bytes(clean)
        return (data, "audio/mpeg") if data else None

    def try_sapi() -> tuple[bytes, str] | None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "speech.wav"
            if _piper_tts(clean, path) or _pyttsx3_tts(clean, path):
                return path.read_bytes(), "audio/wav"
        return None

    # Forced single engine
    forced = {
        "kokoro": [try_kokoro],
        "piper": [try_piper],
        "edge": [try_edge],
        "gtts": [try_gtts],
        "local": [try_sapi],
    }.get(engine)
    if forced:
        for fn in forced:
            hit = fn()
            if hit:
                return hit
        return b"", "text/plain"

    # auto: local neural first (Edge is unreliable / 403), then online, then SAPI
    for fn in (try_kokoro, try_piper, try_edge, try_gtts, try_sapi):
        hit = fn()
        if hit:
            return hit
    return b"", "text/plain"


def synthesize_to_file(text: str, out_path: str | Path, rate: str | None = None) -> Path:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    clean = _scrub(text)
    if not clean:
        out.write_bytes(b"")
        return out

    data, mime = _synthesize_pipeline(clean, rate=rate)
    if data and mime.startswith("audio"):
        ext = ".mp3" if "mpeg" in mime else ".wav"
        path = out.with_suffix(ext)
        path.write_bytes(data)
        return path

    txt = out.with_suffix(".txt")
    txt.write_text(clean, encoding="utf-8")
    return txt


def synthesize_bytes(
    text: str,
    rate: str | None = None,
    *,
    allow_local: bool = True,
    voice: str | None = None,
    engine: str | None = None,
) -> tuple[bytes, str]:
    """Return audio bytes for the HTTP speak API.

    Optional ``voice`` / ``engine`` override prefs (Systems voice preview).
    """
    clean = _scrub(text)
    if not clean:
        return b"", "text/plain"

    data, mime = _synthesize_pipeline(clean, rate=rate, voice=voice, engine=engine)
    if data:
        return data, mime
    if not allow_local:
        return b"", "text/plain"
    return b"", "text/plain"
