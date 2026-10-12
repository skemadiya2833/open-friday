"""One-shot webcam grab. Device is opened and released inside the call."""

from __future__ import annotations

import base64
import time
from dataclasses import dataclass
from typing import Any

from friday.camera.session import camera_backend, camera_index, get_camera_session


@dataclass
class CaptureResult:
    ok: bool
    jpeg_b64: str = ""
    width: int = 0
    height: int = 0
    bytes_len: int = 0
    duration_ms: float = 0.0
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "width": self.width,
            "height": self.height,
            "bytes_len": self.bytes_len,
            "duration_ms": self.duration_ms,
            "error": self.error,
            # never include jpeg_b64 in status/audit payloads
        }


def opencv_available() -> bool:
    try:
        import cv2  # noqa: F401

        return True
    except Exception:
        return False


def capture_jpeg_b64(*, index: int | None = None) -> CaptureResult:
    """Grab a single JPEG frame. Requires an active camera arm grant."""
    session = get_camera_session()
    if not session.is_armed():
        return CaptureResult(ok=False, error="Camera is not armed. Arm it in Systems settings first.")
    if not opencv_available():
        return CaptureResult(
            ok=False,
            error="OpenCV not installed. Run: pip install -r requirements/camera.lock.txt",
        )

    try:
        import cv2
    except Exception as exc:  # noqa: BLE001
        return CaptureResult(ok=False, error=f"OpenCV import failed: {exc}")

    idx = camera_index() if index is None else int(index)
    preferred = camera_backend() if index is None else ""
    t0 = time.perf_counter()
    session.set_live(True)
    try:
        try:
            from friday.ui import overlay

            overlay.set_status("camera live")
        except Exception:  # noqa: BLE001
            pass

        from friday.camera.devices import _open_capture, _restore_opencv_logs, _silence_opencv_logs

        prev_log = _silence_opencv_logs()
        try:
            # Systems-selected backend first — MSMF vs DSHOW indices are not interchangeable.
            cap, used_backend = _open_capture(idx, preferred=preferred or None)
        finally:
            _restore_opencv_logs(prev_log)
        if cap is None or not cap.isOpened():
            hint = f" ({preferred})" if preferred else ""
            return CaptureResult(
                ok=False,
                error=f"Could not open camera index {idx}{hint}. Rescan in Systems and pick the device again.",
            )

        try:
            # Warm up a couple of frames (drivers often return a black first frame).
            frame = None
            for _ in range(5):
                ok, frame = cap.read()
                if ok and frame is not None:
                    break
            if frame is None:
                return CaptureResult(ok=False, error="Camera opened but returned no frame")

            h, w = int(frame.shape[0]), int(frame.shape[1])
            ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
            if not ok:
                return CaptureResult(ok=False, error="JPEG encode failed")
            raw = buf.tobytes()
            b64 = base64.b64encode(raw).decode("ascii")
            ms = round((time.perf_counter() - t0) * 1000, 1)
            return CaptureResult(
                ok=True,
                jpeg_b64=b64,
                width=w,
                height=h,
                bytes_len=len(raw),
                duration_ms=ms,
            )
        finally:
            try:
                cap.release()
            except Exception:  # noqa: BLE001
                pass
    except Exception as exc:  # noqa: BLE001
        return CaptureResult(ok=False, error=f"{type(exc).__name__}: {exc}")
    finally:
        session.set_live(False)
        try:
            from friday.ui import overlay

            overlay.set_status("idle")
        except Exception:  # noqa: BLE001
            pass


def _is_windows() -> bool:
    import sys

    return sys.platform == "win32"
