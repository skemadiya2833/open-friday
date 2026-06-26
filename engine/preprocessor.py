"""
Image preprocessing for Friday.

NPU acceleration via ONNX Runtime is not viable for a single Resize operation —
VitisAI and OpenVINO only offload neural network ops (conv, attention, matmul).
A Resize node always falls back to CPU regardless of the listed provider, giving
the illusion of NPU use while adding ONNX overhead for no gain.

This module uses Pillow (LANCZOS) directly. It is fast enough for 1080p -> 1120px
resizes and gives correct, predictable results. If a real vision encoder is added
in the future, the ONNX session should be introduced here with a proper .onnx model
that contains actual neural network ops the NPU can schedule.
"""

from __future__ import annotations

import base64
from io import BytesIO

from PIL import Image

from config import PREPROCESS_TARGET_SIZE
from engine.coordinates import fit_image_size


_preprocessor: "ImagePreprocessor | None" = None


def get_preprocessor() -> "ImagePreprocessor":
    global _preprocessor
    if _preprocessor is None:
        _preprocessor = ImagePreprocessor()
    return _preprocessor


class ImagePreprocessor:
    def __init__(self) -> None:
        print("[Preprocessor] Using Pillow (LANCZOS) — CPU")

    @property
    def backend(self) -> str:
        return "pillow"

    @property
    def provider(self) -> str | None:
        return None

    def prepare(
        self,
        screenshot_pil: Image.Image,
        target_size: tuple[int, int] = PREPROCESS_TARGET_SIZE,
    ) -> tuple[bytes, tuple[int, int]]:
        """
        Resize screenshot to fit within target_size preserving aspect ratio.
        Returns PNG bytes and the actual output size (width, height).

        The returned size is what the model sees. It must be passed as
        image_size into get_next_steps so coordinate scaling is correct.
        """
        fitted_size = fit_image_size(screenshot_pil.size, target_size)
        resized = screenshot_pil.convert("RGB").resize(fitted_size, Image.Resampling.LANCZOS)
        png_bytes = self._encode_png(resized)
        return png_bytes, resized.size

    def prepare_base64(
        self,
        screenshot_pil: Image.Image,
        target_size: tuple[int, int] = PREPROCESS_TARGET_SIZE,
    ) -> tuple[str, tuple[int, int]]:
        """
        Same as prepare() but returns base64-encoded PNG string and output size.
        image_size is (width, height) in pixels — pass this directly to get_next_steps.
        """
        png_bytes, size = self.prepare(screenshot_pil, target_size)
        return base64.b64encode(png_bytes).decode("utf-8"), size

    @staticmethod
    def _encode_png(image: Image.Image) -> bytes:
        buf = BytesIO()
        image.save(buf, format="PNG", optimize=True)
        return buf.getvalue()