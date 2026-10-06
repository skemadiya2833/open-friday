"""Local speech-to-text via faster-whisper (optional dependency)."""

from __future__ import annotations

import os
import tempfile
import threading
import warnings
from pathlib import Path

import numpy as np

from friday.config import VOICE_STT_MODEL

# Quiet HuggingFace cache warnings on Windows (no symlink support without Dev Mode).
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

_TARGET_SR = 16000
_model = None


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        # Provisional default: large-v3-turbo, float16 on CUDA (verified to load and run on the
        # RTX 5060 Ti; accuracy on the owner's real speech is UNVERIFIED, see docs/research/stt_bench.json).
        # Falls back to CPU int8 if CUDA or the model cannot be loaded. Override with
        # VOICE_STT_DEVICE=cpu|cuda|auto and VOICE_STT_COMPUTE=float16|int8|int8_float16.
        device = os.getenv("VOICE_STT_DEVICE", "auto").lower()
        compute = os.getenv("VOICE_STT_COMPUTE", "float16")
        attempts = []
        if device in ("auto", "cuda"):
            attempts.append(("cuda", compute))
        attempts.append(("cpu", "int8"))
        last: Exception | None = None
        for dev, ct in attempts:
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    _model = WhisperModel(VOICE_STT_MODEL, device=dev, compute_type=ct)
                print(f"[STT] {VOICE_STT_MODEL} on {dev} ({ct})")
                break
            except Exception as exc:  # noqa: BLE001
                last = exc
                print(f"[STT] {VOICE_STT_MODEL} on {dev}/{ct} failed: {exc}")
        if _model is None:
            raise RuntimeError(f"could not load STT model: {last}")
    return _model


def _decode_audio(path: str | Path) -> np.ndarray:
    """
    Decode any browser-recorded blob (usually webm/opus) to 16 kHz mono float32.

    Avoids faster-whisper's av.open(..., metadata_errors=...) which breaks on
    some Windows PyAV builds.
    """
    path = str(path)

    # 1) Prefer ffmpeg if available (most reliable for webm).
    import shutil
    import subprocess

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        wav_path = path + ".16k.wav"
        try:
            subprocess.run(
                [
                    ffmpeg, "-y", "-loglevel", "error",
                    "-i", path,
                    "-ac", "1", "-ar", str(_TARGET_SR),
                    "-f", "wav", wav_path,
                ],
                check=True,
                timeout=60,
            )
            import wave

            with wave.open(wav_path, "rb") as wf:
                frames = wf.readframes(wf.getnframes())
                audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
            return audio
        except Exception as exc:
            print(f"[STT] ffmpeg decode failed: {exc}")
        finally:
            Path(wav_path).unlink(missing_ok=True)

    # 2) PyAV without the incompatible metadata_errors kwarg.
    try:
        import av

        container = av.open(path, mode="r")
        try:
            resampler = av.audio.resampler.AudioResampler(
                format="flt", layout="mono", rate=_TARGET_SR,
            )
            chunks: list[np.ndarray] = []
            for frame in container.decode(audio=0):
                for out in resampler.resample(frame):
                    arr = out.to_ndarray()
                    if arr.ndim > 1:
                        arr = arr.reshape(-1)
                    chunks.append(arr.astype(np.float32, copy=False))
            # Flush resampler
            for out in resampler.resample(None):
                arr = out.to_ndarray()
                if arr.ndim > 1:
                    arr = arr.reshape(-1)
                chunks.append(arr.astype(np.float32, copy=False))
            if not chunks:
                raise RuntimeError("No audio frames decoded")
            return np.concatenate(chunks)
        finally:
            container.close()
    except Exception as exc:
        raise RuntimeError(
            "Could not decode microphone audio. Install ffmpeg and ensure it is on PATH, "
            f"or upgrade PyAV. Detail: {exc}"
        ) from exc


_infer_lock = threading.Lock()


def transcribe_array(audio: np.ndarray) -> str:
    """16 kHz mono float32 in [-1, 1]. Serialised: streaming partials and finals share one model."""
    if audio.size == 0:
        return ""
    model = _get_model()
    with _infer_lock:
        segments, _info = model.transcribe(audio.astype(np.float32, copy=False), language="en", beam_size=1,
                                           vad_filter=False, condition_on_previous_text=False)
        return " ".join(s.text.strip() for s in segments).strip()


def transcribe_file(path: str | Path) -> str:
    audio = _decode_audio(path)
    if audio.size == 0:
        return ""
    model = _get_model()
    segments, _info = model.transcribe(audio, language="en", beam_size=1)
    return " ".join(s.text.strip() for s in segments).strip()


def transcribe_bytes(data: bytes, suffix: str = ".webm") -> str:
    if not data:
        return ""
    # Browser MediaRecorder usually sends webm; keep a real suffix for demuxers.
    if suffix in (".wav", ".webm", ".ogg", ".mp3", ".m4a", ".mp4"):
        use_suffix = suffix
    else:
        use_suffix = ".webm"
    with tempfile.NamedTemporaryFile(suffix=use_suffix, delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name
    try:
        return transcribe_file(tmp_path)
    finally:
        Path(tmp_path).unlink(missing_ok=True)
