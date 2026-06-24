"""
NPU-accelerated image preprocessing with graceful CPU / Pillow fallback.

Tries ONNX Runtime execution providers in order:
  VitisAI (AMD Ryzen AI) -> OpenVINO (Intel NPU / iGPU) -> CPU -> Pillow
"""

from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path

from PIL import Image

from config import NPU_PREPROCESSING, PREPROCESS_TARGET_SIZE
from engine.coordinates import fit_image_size

_MODEL_PATH = Path(__file__).parent / "assets" / "preprocess.onnx"

_preprocessor: "ImagePreprocessor | None" = None


def get_preprocessor() -> "ImagePreprocessor":
    global _preprocessor
    if _preprocessor is None:
        _preprocessor = ImagePreprocessor()
    return _preprocessor


def _create_resize_model(path: Path) -> bool:
    """Build a dynamic-size Resize ONNX graph. Requires the `onnx` package."""
    try:
        import onnx
        from onnx import helper, TensorProto
    except ImportError:
        return False

    path.parent.mkdir(parents=True, exist_ok=True)

    input_tensor = helper.make_tensor_value_info(
        "input", TensorProto.FLOAT, [1, 3, "height", "width"]
    )
    sizes_input = helper.make_tensor_value_info("sizes", TensorProto.INT64, [4])
    output_tensor = helper.make_tensor_value_info(
        "output", TensorProto.FLOAT, [1, 3, "out_height", "out_width"]
    )

    resize = helper.make_node(
        "Resize",
        inputs=["input", "", "", "sizes"],
        outputs=["output"],
        mode="linear",
        coordinate_transformation_mode="half_pixel",
    )

    graph = helper.make_graph(
        [resize], "preprocess", [input_tensor, sizes_input], [output_tensor]
    )
    model = helper.make_model(
        graph, opset_imports=[helper.make_opsetid("", 13)]
    )
    onnx.save(model, str(path))
    return True


def _detect_provider() -> tuple[str | None, object | None]:
    if not NPU_PREPROCESSING:
        return None, None
    try:
        import onnxruntime as ort
    except ImportError:
        return None, None

    available = ort.get_available_providers()
    for provider in (
        "VitisAIExecutionProvider",
        "OpenVINOExecutionProvider",
        "CPUExecutionProvider",
    ):
        if provider in available:
            return provider, ort
    return None, ort


class ImagePreprocessor:
    def __init__(self) -> None:
        self._provider: str | None = None
        self._session = None
        self._backend = "pillow"

        provider, ort = _detect_provider()
        if provider and ort is not None:
            if not _MODEL_PATH.exists():
                _create_resize_model(_MODEL_PATH)
            if _MODEL_PATH.exists():
                try:
                    self._session = ort.InferenceSession(
                        str(_MODEL_PATH),
                        providers=[provider],
                    )
                    self._provider = provider
                    self._backend = "onnx"
                except Exception:
                    self._session = None

        if self._backend == "onnx":
            print(f"[Preprocessor] Using ONNX Runtime ({self._provider})")
        else:
            print("[Preprocessor] Using Pillow (CPU)")

    @property
    def backend(self) -> str:
        return self._backend

    @property
    def provider(self) -> str | None:
        return self._provider

    def prepare(
        self,
        screenshot_pil: Image.Image,
        target_size: tuple[int, int] = PREPROCESS_TARGET_SIZE,
    ) -> tuple[bytes, tuple[int, int]]:
        """
        Resize and normalise a screenshot, returning PNG bytes and output size.
        """
        fitted_size = fit_image_size(screenshot_pil.size, target_size)
        if self._session is not None:
            try:
                return self._prepare_onnx(screenshot_pil, fitted_size)
            except Exception:
                pass
        return self._prepare_pillow(screenshot_pil, fitted_size)

    def prepare_base64(
        self,
        screenshot_pil: Image.Image,
        target_size: tuple[int, int] = PREPROCESS_TARGET_SIZE,
    ) -> tuple[str, tuple[int, int]]:
        png_bytes, size = self.prepare(screenshot_pil, target_size)
        return base64.b64encode(png_bytes).decode("utf-8"), size

    def _prepare_onnx(
        self, image: Image.Image, target_size: tuple[int, int]
    ) -> tuple[bytes, tuple[int, int]]:
        import numpy as np

        rgb = image.convert("RGB")
        arr = np.asarray(rgb, dtype=np.float32) / 255.0
        nchw = np.transpose(arr, (2, 0, 1))[np.newaxis, ...]
        target_w, target_h = target_size
        sizes = np.array([1, 3, target_h, target_w], dtype=np.int64)

        output = self._session.run(None, {"input": nchw, "sizes": sizes})[0]
        hwc = np.transpose(output[0], (1, 2, 0))
        uint8 = (np.clip(hwc, 0.0, 1.0) * 255).astype(np.uint8)
        out_image = Image.fromarray(uint8)
        return self._encode_png(out_image), out_image.size

    def _prepare_pillow(
        self, image: Image.Image, target_size: tuple[int, int]
    ) -> tuple[bytes, tuple[int, int]]:
        resized = image.convert("RGB").resize(target_size, Image.Resampling.LANCZOS)
        return self._encode_png(resized), resized.size

    @staticmethod
    def _encode_png(image: Image.Image) -> bytes:
        buffered = BytesIO()
        image.save(buffered, format="PNG", optimize=True)
        return buffered.getvalue()
