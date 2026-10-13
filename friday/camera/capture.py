"""One-shot webcam grab. Device is opened and released inside the call."""

from __future__ import annotations

import base64
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
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
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "width": self.width,
            "height": self.height,
            "bytes_len": self.bytes_len,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "source": self.source,
            # never include jpeg_b64 in status/audit payloads
        }


def opencv_available() -> bool:
    try:
        import cv2  # noqa: F401

        return True
    except Exception:
        return False


def _capture_ffmpeg_by_name(name: str, *, width: int = 0, height: int = 0) -> CaptureResult:
    """Grab via DirectShow device *name* (bypasses OpenCV index confusion)."""
    ff = shutil.which("ffmpeg")
    if not ff or not (name or "").strip():
        return CaptureResult(ok=False, error="ffmpeg unavailable")
    clean = name.strip()
    tmp: Path | None = None
    t0 = time.perf_counter()
    try:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            tmp = Path(f.name)
        # Try requested size first, then driver default.
        attempts: list[list[str]] = []
        if width and height:
            attempts.append(
                [
                    ff, "-hide_banner", "-loglevel", "error",
                    "-f", "dshow", "-video_size", f"{width}x{height}",
                    "-i", f"video={clean}",
                    "-frames:v", "1", "-y", str(tmp),
                ]
            )
        attempts.append(
            [
                ff, "-hide_banner", "-loglevel", "error",
                "-f", "dshow",
                "-i", f"video={clean}",
                "-frames:v", "1", "-y", str(tmp),
            ]
        )
        last_err = ""
        for cmd in attempts:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
            proc = subprocess.run(cmd, capture_output=True, timeout=20, check=False)  # noqa: S603
            if proc.returncode == 0 and tmp.is_file() and tmp.stat().st_size > 100:
                raw = tmp.read_bytes()
                w = h = 0
                try:
                    import cv2
                    import numpy as np

                    arr = np.frombuffer(raw, dtype=np.uint8)
                    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                    if img is not None:
                        h, w = int(img.shape[0]), int(img.shape[1])
                except Exception:  # noqa: BLE001
                    pass
                ms = round((time.perf_counter() - t0) * 1000, 1)
                return CaptureResult(
                    ok=True,
                    jpeg_b64=base64.b64encode(raw).decode("ascii"),
                    width=w,
                    height=h,
                    bytes_len=len(raw),
                    duration_ms=ms,
                    source=f"ffmpeg:{clean}",
                )
            last_err = (proc.stderr or b"").decode("utf-8", "replace")[:200]
        return CaptureResult(ok=False, error=last_err or f"ffmpeg could not open video={clean}")
    except Exception as exc:  # noqa: BLE001
        return CaptureResult(ok=False, error=f"ffmpeg: {exc}")
    finally:
        if tmp is not None:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:  # noqa: BLE001
                pass


def capture_jpeg_b64(*, index: int | None = None) -> CaptureResult:
    """Grab a single JPEG frame. Requires an active camera arm grant.

    Prefer ffmpeg DirectShow capture by saved device **name** (stable). OpenCV index
    is a fallback only — MSMF/DSHOW indices remapped devices and mislabeled PnP names.
    """
    session = get_camera_session()
    if not session.is_armed():
        return CaptureResult(ok=False, error="Camera is not armed. Arm it in Systems settings first.")

    from friday.camera.devices import load_resolution_wh, load_selected_name

    want_w, want_h = load_resolution_wh()
    device_name = load_selected_name()
    t0 = time.perf_counter()
    session.set_live(True)
    try:
        try:
            from friday.ui import overlay

            overlay.set_status("camera live")
        except Exception:  # noqa: BLE001
            pass

        # 1) Name-based capture — correct device even when OpenCV indices lie.
        ff_err = ""
        if device_name:
            ff = _capture_ffmpeg_by_name(device_name, width=want_w, height=want_h)
            if ff.ok:
                return ff
            ff_err = ff.error or ""

        if not opencv_available():
            return CaptureResult(
                ok=False,
                error=ff_err
                or "OpenCV not installed. Run: pip install -r requirements/camera.lock.txt",
            )

        try:
            import cv2
        except Exception as exc:  # noqa: BLE001
            return CaptureResult(ok=False, error=f"OpenCV import failed: {exc}")

        idx = camera_index() if index is None else int(index)
        preferred = camera_backend() if index is None else ""

        from friday.camera.devices import (
            _open_capture,
            _restore_opencv_logs,
            _silence_opencv_logs,
            apply_capture_resolution,
        )

        prev_log = _silence_opencv_logs()
        try:
            cap, _used_backend = _open_capture(idx, preferred=preferred or None)
        finally:
            _restore_opencv_logs(prev_log)
        if cap is None or not cap.isOpened():
            hint = f" ({preferred})" if preferred else ""
            err = f"Could not open camera index {idx}{hint}."
            if device_name:
                err += f" Name capture also failed for '{device_name}'."
            return CaptureResult(ok=False, error=err + " Rescan in Systems and pick the device again.")

        try:
            apply_capture_resolution(cap, width=want_w, height=want_h)
            frame = None
            for _ in range(8):
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
                source=f"opencv:{preferred or 'auto'}:{idx}",
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
