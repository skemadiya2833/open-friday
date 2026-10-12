"""Wake word via openWakeWord (Apache-2.0), ONNX runtime only (the tflite path is not used on Windows).

Pretrained models shipped by openWakeWord: alexa, hey_mycroft, hey_jarvis, hey_rhasspy, timer, weather.
There is NO pretrained "hey friday". Default is ``hey_jarvis`` (closest feel); a custom model can be
trained with openWakeWord's synthetic-data pipeline and passed as a path. Custom-model accuracy is
UNVERIFIED because it needs the owner's voice.

Frames: 1280 samples (80 ms) of 16 kHz int16 audio.
"""

from __future__ import annotations

import os
from typing import Iterable

import numpy as np

FRAME = 1280


class WakeWord:
    def __init__(self, model: str | None = None, threshold: float | None = None) -> None:
        import openwakeword
        from openwakeword.model import Model

        self.model_name = model or os.getenv("WAKE_WORD_MODEL", "hey_jarvis")
        self.threshold = float(threshold if threshold is not None else os.getenv("WAKE_WORD_THRESHOLD", "0.5"))
        paths = [self.model_name]
        if not os.path.isfile(self.model_name):
            paths = [p for p in openwakeword.get_pretrained_model_paths("onnx") if self.model_name in os.path.basename(p)]
            if not paths:
                raise FileNotFoundError(f"wake word model '{self.model_name}' not found; run scripts/voice_setup.py")
        self._m = Model(wakeword_models=paths, inference_framework="onnx")
        self._key = next(iter(self._m.models.keys()))

    def reset(self) -> None:
        self._m.reset()

    def score(self, frame_i16: np.ndarray) -> float:
        if frame_i16.dtype != np.int16 or frame_i16.shape[-1] != FRAME:
            raise ValueError(f"need {FRAME} int16 samples")
        return float(self._m.predict(frame_i16).get(self._key, 0.0))

    def detect(self, frame_i16: np.ndarray) -> bool:
        return self.score(frame_i16) >= self.threshold

    def scan(self, audio_i16: np.ndarray) -> Iterable[tuple[int, float]]:
        """Yield (frame_index, score) for a whole clip (used by the benchmark and tests)."""
        for i in range(0, len(audio_i16) - FRAME + 1, FRAME):
            yield i // FRAME, self.score(audio_i16[i:i + FRAME])
