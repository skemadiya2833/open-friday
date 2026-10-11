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


def _edge_tts(text: str, out: Path, rate: str | None = None) -> bool:
    try:
        import edge_tts
    except ImportError:
        return False

    rate_s = _normalize_rate(rate)
    candidates: list[str] = []
    primary = _resolve_edge_voice(VOICE_TTS_VOICE)
    candidates.append(primary)
    for alt in _EDGE_FALLBACKS:
        if alt not in candidates:
            candidates.append(alt)

    async def _run(voice: str, dest: Path) -> None:
        communicate = edge_tts.Communicate(text, voice, rate=rate_s)
        await communicate.save(str(dest))

    last_err = None
    for voice in candidates:
        raw: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                raw = Path(tmp.name)
            asyncio.run(_run(voice, raw))
            if not (raw.exists() and raw.stat().st_size > 44):
                raise RuntimeError("empty audio")
            raw.replace(out)
            return out.exists() and out.stat().st_size > 44
        except Exception as exc:
            last_err = exc
            print(f"[TTS] edge-tts {voice} failed: {exc}")
        finally:
            if raw is not None:
                raw.unlink(missing_ok=True)
    if last_err:
        print(f"[TTS] edge-tts exhausted: {last_err}")
    return False


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
    with tempfile.TemporaryDirectory() as tmp:
        path = synthesize_to_file(text, Path(tmp) / "speech.wav", rate=rate)
        data = path.read_bytes()
        if path.suffix == ".mp3":
            mime = "audio/mpeg"
        elif path.suffix == ".wav":
            mime = "audio/wav"
        else:
            mime = "text/plain"
        return data, mime
