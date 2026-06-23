import mss
import base64
from io import BytesIO
from PIL import Image
from config import PRIMARY_MONITOR_INDEX


def capture_screen() -> tuple[str, tuple[int, int]]:
    """
    Captures the primary monitor.
    Returns a tuple of (base64_png_string, (width, height)).
    """
    with mss.mss() as sct:
        monitor = sct.monitors[PRIMARY_MONITOR_INDEX]
        screenshot = sct.grab(monitor)

        img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
        buffered = BytesIO()
        img.save(buffered, format="PNG")

        img_b64 = base64.b64encode(buffered.getvalue()).decode("utf-8")
        return img_b64, (monitor["width"], monitor["height"])