"""Pillow-based screenshot preprocessing for the VLM."""

from __future__ import annotations

import base64
from io import BytesIO

from PIL import Image

from friday.actions.coordinates import fit_image_size
from friday.config import (
    PREPROCESS_FORMAT,
    PREPROCESS_JPEG_QUALITY,
    PREPROCESS_RESAMPLE,
    PREPROCESS_TARGET_SIZE,
)

_preprocessor: "ImagePreprocessor | None" = None

_RESAMPLE_MAP = {
    "lanczos": Image.Resampling.LANCZOS,
    "bilinear": Image.Resampling.BILINEAR,
    "nearest": Image.Resampling.NEAREST,
}


def get_preprocessor() -> "ImagePreprocessor":
    global _preprocessor
    if _preprocessor is None:
        _preprocessor = ImagePreprocessor()
    return _preprocessor


class ImagePreprocessor:
    def __init__(self) -> None:
        resample = _RESAMPLE_MAP.get(PREPROCESS_RESAMPLE, Image.Resampling.LANCZOS)
        self._resample = resample
        print(
            f"[Preprocessor] Pillow ({PREPROCESS_RESAMPLE}) → {PREPROCESS_FORMAT.upper()} — CPU"
        )

    @property
    def backend(self) -> str:
        return "pillow"

    def prepare(
        self,
        screenshot_pil: Image.Image,
        target_size: tuple[int, int] = PREPROCESS_TARGET_SIZE,
    ) -> tuple[bytes, tuple[int, int]]:
        fitted_size = fit_image_size(screenshot_pil.size, target_size)
        if fitted_size == screenshot_pil.size and screenshot_pil.mode == "RGB":
            working = screenshot_pil
        else:
            working = screenshot_pil.convert("RGB").resize(fitted_size, self._resample)

        buf = BytesIO()
        if PREPROCESS_FORMAT == "jpeg":
            working.save(
                buf,
                format="JPEG",
                quality=PREPROCESS_JPEG_QUALITY,
                optimize=False,
            )
        else:
            working.save(buf, format="PNG", optimize=False)
        return buf.getvalue(), working.size

    def prepare_base64(
        self,
        screenshot_pil: Image.Image,
        target_size: tuple[int, int] = PREPROCESS_TARGET_SIZE,
    ) -> tuple[str, tuple[int, int]]:
        image_bytes, size = self.prepare(screenshot_pil, target_size)
        return base64.b64encode(image_bytes).decode("utf-8"), size
