"""Local text-to-speech: edge-tts (preferred) → pyttsx3 → plain text."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import tempfile
from pathlib import Path

from friday.config import VOICE_TTS_VOICE
from friday.persona import DEFAULT_EDGE_VOICE


def _resolve_edge_voice(configured: str) -> str:
    """Map Piper-style names / blanks to a female MCU-Friday-like edge voice."""
    v = (configured or "").strip()
    if not v or "en_US" in v or v.endswith("-medium") or v.endswith(".onnx"):
        return DEFAULT_EDGE_VOICE
    if v.startswith("en-") and "Neural" in v:
        return v
    return DEFAULT_EDGE_VOICE


def _edge_tts(text: str, out: Path) -> bool:
    try:
        import edge_tts
    except ImportError:
        return False

    # Prefer Irish female (MCU Friday vibe); fall back to British female.
    candidates = []
    primary = _resolve_edge_voice(VOICE_TTS_VOICE)
    candidates.append(primary)
    for alt in ("en-IE-EmilyNeural", "en-GB-SoniaNeural", "en-US-AriaNeural"):
        if alt not in candidates:
            candidates.append(alt)

    async def _run(voice: str, dest: Path) -> None:
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(str(dest))

    last_err = None
    for voice in candidates:
        raw: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                raw = Path(tmp.name)
            # Fresh event loop per attempt avoids flaky Windows edge-tts runs.
            asyncio.run(_run(voice, raw))
            if not (raw.exists() and raw.stat().st_size > 44):
                raise RuntimeError("empty audio")
            # Slightly slower delivery (~10%) via ffmpeg time-stretch.
            if _slow_audio(raw, out, tempo=0.90):
                return True
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


def _slow_audio(src: Path, dest: Path, *, tempo: float = 0.90) -> bool:
    """Time-stretch speech a bit (atempo range 0.5–2.0)."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False
    tempo = max(0.5, min(2.0, float(tempo)))
    try:
        subprocess.run(
            [
                ffmpeg, "-y", "-loglevel", "error",
                "-i", str(src),
                "-filter:a", f"atempo={tempo}",
                str(dest),
            ],
            check=True,
            timeout=60,
        )
        return dest.exists() and dest.stat().st_size > 44
    except Exception as exc:
        print(f"[TTS] atempo slowdown failed: {exc}")
        return False


def _piper_tts(text: str, out: Path) -> bool:
    piper = shutil.which("piper")
    if not piper:
        return False
    # Piper only if an explicit piper model path/name was configured.
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
        # Prefer a female SAPI voice when available.
        try:
            for voice in engine.getProperty("voices") or []:
                name = f"{getattr(voice, 'name', '')} {getattr(voice, 'id', '')}".lower()
                if any(k in name for k in ("zira", "female", "eva", "hazel", "susan")):
                    engine.setProperty("voice", voice.id)
                    break
        except Exception:
            pass
        engine.setProperty("rate", 155)
        engine.save_to_file(text, str(wav.resolve()))
        engine.runAndWait()
        if wav.exists() and wav.stat().st_size > 44:
            if wav != out:
                wav.replace(out)
            return True
    except Exception as exc:
        print(f"[TTS] pyttsx3 fallback failed: {exc}")
    return False


def synthesize_to_file(text: str, out_path: str | Path) -> Path:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    clean = (text or "").strip()
    if not clean:
        out.write_bytes(b"")
        return out

    mp3 = out.with_suffix(".mp3")
    if _edge_tts(clean, mp3):
        return mp3

    wav = out.with_suffix(".wav")
    if _piper_tts(clean, wav):
        return wav
    if _pyttsx3_tts(clean, wav):
        return wav

    txt = out.with_suffix(".txt")
    txt.write_text(clean, encoding="utf-8")
    return txt


def synthesize_bytes(text: str) -> tuple[bytes, str]:
    with tempfile.TemporaryDirectory() as tmp:
        path = synthesize_to_file(text, Path(tmp) / "speech.wav")
        data = path.read_bytes()
        if path.suffix == ".mp3":
            mime = "audio/mpeg"
        elif path.suffix == ".wav":
            mime = "audio/wav"
        else:
            mime = "text/plain"
        return data, mime
