"""Text-to-speech: edge-tts neural (preferred) → pyttsx3 → plain text.

Speaker+mic setups (monitor speakers + desk mic) cannot rely on browser AEC —
half-duplex in the UI mutes STT while we play. Keep synthesis at a natural rate
(+0% by default); only nudge rate when the owner asks to slow down / speed up.
"""

from __future__ import annotations

import asyncio
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from friday.config import VOICE_TTS_VOICE
from friday.persona import DEFAULT_EDGE_VOICE

# Natural conversational females first; Emily kept as a late fallback only.
_EDGE_FALLBACKS = (
    "en-US-AvaNeural",
    "en-US-JennyNeural",
    "en-US-AriaNeural",
    "en-GB-SoniaNeural",
    "en-IE-EmilyNeural",
)


def _resolve_edge_voice(configured: str) -> str:
    v = (configured or "").strip()
    if not v or "en_US" in v or v.endswith("-medium") or v.endswith(".onnx"):
        return DEFAULT_EDGE_VOICE
    if v.startswith("en-") and "Neural" in v:
        return v
    return DEFAULT_EDGE_VOICE


def _normalize_rate(rate: str | None) -> str:
    """Edge expects e.g. +0%, -15%, +20%. Reject weird values → natural."""
    r = (rate or "+0%").strip()
    if re.fullmatch(r"[+-]?\d{1,3}%", r):
        n = int(r.rstrip("%"))
        n = max(-50, min(50, n))
        return f"{n:+d}%"
    return "+0%"


def _edge_voice_candidates() -> list[str]:
    voice_name = VOICE_TTS_VOICE
    try:
        from friday.runtime.prefs import get as pref

        voice_name = str(pref("tts_voice") or VOICE_TTS_VOICE)
    except Exception:  # noqa: BLE001
        pass
    primary = _resolve_edge_voice(voice_name)
    out = [primary]
    for alt in _EDGE_FALLBACKS:
        if alt not in out:
            out.append(alt)
    return out


async def _edge_bytes(text: str, voice: str, rate_s: str) -> bytes:
    """Synthesize in memory (no tempfile) — lower TTS start latency."""
    import edge_tts

    communicate = edge_tts.Communicate(text, voice, rate=rate_s)
    chunks: list[bytes] = []
    async for part in communicate.stream():
        if part.get("type") == "audio" and part.get("data"):
            chunks.append(part["data"])
    return b"".join(chunks)


def _edge_tts_bytes(text: str, rate: str | None = None) -> bytes | None:
    try:
        import edge_tts  # noqa: F401
    except ImportError:
        return None

    rate_s = _normalize_rate(rate)
    last_err = None
    for voice in _edge_voice_candidates():
        try:
            data = asyncio.run(_edge_bytes(text, voice, rate_s))
            if data and len(data) > 44:
                return data
            raise RuntimeError("empty audio")
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            print(f"[TTS] edge-tts {voice} failed: {exc}")
    if last_err:
        print(f"[TTS] edge-tts exhausted: {last_err}")
    return None


def _edge_tts(text: str, out: Path, rate: str | None = None) -> bool:
    data = _edge_tts_bytes(text, rate=rate)
    if not data:
        return False
    out.write_bytes(data)
    return out.exists() and out.stat().st_size > 44


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


def _pyttsx3_tts(text: str, out: Path) -> bool:
    try:
        import pyttsx3

        wav = out if out.suffix.lower() == ".wav" else out.with_suffix(".wav")
        engine = pyttsx3.init()
        try:
            for voice in engine.getProperty("voices") or []:
                name = f"{getattr(voice, 'name', '')} {getattr(voice, 'id', '')}".lower()
                if any(k in name for k in ("zira", "female", "eva", "hazel", "susan")):
                    engine.setProperty("voice", voice.id)
                    break
        except Exception:
            pass
        engine.setProperty("rate", 175)  # closer to natural speech than 195
        engine.save_to_file(text, str(wav.resolve()))
        engine.runAndWait()
        if wav.exists() and wav.stat().st_size > 44:
            if wav != out:
                wav.replace(out)
            return True
    except Exception as exc:
        print(f"[TTS] pyttsx3 fallback failed: {exc}")
    return False


def synthesize_to_file(text: str, out_path: str | Path, rate: str | None = None) -> Path:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    clean = (text or "").strip()
    if not clean:
        out.write_bytes(b"")
        return out
    # Scan before speech (not post-hoc) — never speak raw secrets.
    try:
        from friday.security.content_scan import scan_speech

        spoken = scan_speech(clean)
        if spoken.blocked:
            clean = "I can't say that out loud — it looked like a secret."
        else:
            clean = spoken.text.strip() or clean
    except Exception:
        pass

    mp3 = out.with_suffix(".mp3")
    if _edge_tts(clean, mp3, rate=rate):
        return mp3

    wav = out.with_suffix(".wav")
    if _piper_tts(clean, wav):
        return wav
    if _pyttsx3_tts(clean, wav):
        return wav

    txt = out.with_suffix(".txt")
    txt.write_text(clean, encoding="utf-8")
    return txt


def synthesize_bytes(text: str, rate: str | None = None) -> tuple[bytes, str]:
    clean = (text or "").strip()
    if not clean:
        return b"", "text/plain"
    try:
        from friday.security.content_scan import scan_speech

        spoken = scan_speech(clean)
        if spoken.blocked:
            clean = "I can't say that out loud — it looked like a secret."
        else:
            clean = spoken.text.strip() or clean
    except Exception:  # noqa: BLE001
        pass

    # Fast path: Edge MP3 in memory (skips tempfile round-trip).
    edge = _edge_tts_bytes(clean, rate=rate)
    if edge:
        return edge, "audio/mpeg"

    with tempfile.TemporaryDirectory() as tmp:
        path = synthesize_to_file(clean, Path(tmp) / "speech.wav", rate=rate)
        data = path.read_bytes()
        if path.suffix == ".mp3":
            mime = "audio/mpeg"
        elif path.suffix == ".wav":
            mime = "audio/wav"
        else:
            mime = "text/plain"
        return data, mime
