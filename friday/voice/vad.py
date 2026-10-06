"""Voice activity detection with the Silero VAD ONNX model (MIT) via onnxruntime. No torch.

The model file ships inside the ``silero-vad`` wheel (``silero_vad/data/silero_vad.onnx``);
``scripts/voice_setup.py`` extracts it. 16 kHz mono, 512-sample frames (32 ms), 64-sample context.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np

FRAME = 512
CONTEXT = 64
SR = 16000


def default_model_path() -> Path:
    env = os.getenv("FRIDAY_VAD_MODEL")
    if env:
        return Path(env)
    from friday.config import DATA_DIR

    return Path(DATA_DIR) / "voice_lab" / "models" / "silero_vad.onnx"


class SileroVad:
    def __init__(self, model_path: str | Path | None = None) -> None:
        import onnxruntime as ort

        path = Path(model_path) if model_path else default_model_path()
        if not path.is_file():
            raise FileNotFoundError(f"Silero VAD model not found at {path}. Run scripts/voice_setup.py")
        so = ort.SessionOptions()
        so.inter_op_num_threads = so.intra_op_num_threads = 1
        self._s = ort.InferenceSession(str(path), sess_options=so, providers=["CPUExecutionProvider"])
        self.reset()

    def reset(self) -> None:
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._ctx = np.zeros((1, CONTEXT), dtype=np.float32)

    def prob(self, frame: np.ndarray) -> float:
        """Speech probability of one 512-sample float32 frame in [-1, 1]."""
        if frame.shape[-1] != FRAME:
            raise ValueError(f"frame must have {FRAME} samples")
        x = np.concatenate([self._ctx, frame.reshape(1, -1).astype(np.float32)], axis=1)
        out, self._state = self._s.run(None, {"input": x, "state": self._state, "sr": np.array(SR, dtype=np.int64)})
        self._ctx = x[:, -CONTEXT:]
        return float(out[0][0])


@dataclass
class EndpointConfig:
    start_prob: float = 0.5
    end_prob: float = 0.35
    start_frames: int = 3            # ~96 ms of speech to open an utterance
    min_silence_ms: int = 700        # silence that ends an utterance
    pre_roll_ms: int = 320
    max_utterance_s: float = 20.0
    min_utterance_ms: int = 300


class Endpointer:
    """Turn a stream of 32 ms frames into utterances. ``feed`` returns an utterance (float32) when one ends."""

    def __init__(self, vad: SileroVad, cfg: EndpointConfig | None = None) -> None:
        self.vad, self.cfg = vad, cfg or EndpointConfig()
        self._ms = FRAME * 1000 / SR
        self.reset()

    def reset(self) -> None:
        self.vad.reset()
        self._pre: list[np.ndarray] = []
        self._buf: list[np.ndarray] = []
        self._in = False
        self._run = 0
        self._sil = 0.0
        self.speech_end_t: float | None = None     # monotonic time (set by the caller via ``now``) of the last speech frame

    @property
    def speaking(self) -> bool:
        return self._in

    def buffered(self) -> np.ndarray:
        """Audio of the utterance in progress (for streaming partial transcripts)."""
        return np.concatenate(self._buf) if self._buf else np.zeros(0, dtype=np.float32)

    def feed(self, frame: np.ndarray, now: float | None = None) -> np.ndarray | None:
        p = self.vad.prob(frame)
        c = self.cfg
        if not self._in:
            self._pre.append(frame)
            keep = max(1, int(c.pre_roll_ms / self._ms))
            self._pre = self._pre[-keep - c.start_frames:]
            self._run = self._run + 1 if p >= c.start_prob else 0
            if self._run >= c.start_frames:
                self._in, self._buf, self._sil = True, list(self._pre), 0.0
            return None
        self._buf.append(frame)
        if p >= c.end_prob:
            self._sil = 0.0
            self.speech_end_t = now
        else:
            self._sil += self._ms
        too_long = len(self._buf) * self._ms >= c.max_utterance_s * 1000
        if self._sil >= c.min_silence_ms or too_long:
            audio = np.concatenate(self._buf)
            dur_ms = len(audio) * 1000 / SR - self._sil
            self._in, self._buf, self._pre, self._run = False, [], [], 0
            self.vad.reset()
            return audio if dur_ms >= c.min_utterance_ms else None
        return None
