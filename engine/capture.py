import mss
import base64
from io import BytesIO
from PIL import Image
from config import PRIMARY_MONITOR_INDEX, NPU_PREPROCESSING, PREPROCESS_TARGET_SIZE


def capture_screen() -> tuple[str, tuple[int, int], tuple[int, int]]:
    """
    Captures the primary monitor.

    Returns:
        base64_png_string,
        native_size (physical monitor pixels),
        image_size (pixels of the image sent to the VLM).
    """
    with mss.mss() as sct:
        monitor = sct.monitors[PRIMARY_MONITOR_INDEX]
        screenshot = sct.grab(monitor)

        img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
        native_size = (monitor["width"], monitor["height"])

        if NPU_PREPROCESSING:
            from engine.preprocessor import get_preprocessor

            preprocessor = get_preprocessor()
            img_b64, image_size = preprocessor.prepare_base64(
                img, target_size=PREPROCESS_TARGET_SIZE
            )
            return img_b64, native_size, image_size

        buffered = BytesIO()
        img.save(buffered, format="PNG")
        img_b64 = base64.b64encode(buffered.getvalue()).decode("utf-8")
        return img_b64, native_size, native_size
