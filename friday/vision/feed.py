"""Continuous live screen observation for the vision model."""

from __future__ import annotations

import base64
import shutil
import subprocess
import tempfile
import threading
import time
from collections import deque
from pathlib import Path
from typing import Literal

from PIL import Image, ImageDraw

from friday.config import (
    GUI_LIVE_EMIT_INTERVAL,
    HIDE_UI_FROM_CAPTURE,
    LIVE_PREVIEW_FPS,
    OVERLAY_ENABLED,
    PREPROCESS_TARGET_SIZE,
    PRIMARY_MONITOR_INDEX,
    STREAM_FRAME_COUNT,
    STREAM_USE_VIDEO,
    STREAM_VIDEO_FPS,
    STREAM_VIDEO_SECONDS,
    should_store_frame_pil,
)
from friday.types import FramePacket, VisionPayload

# Fallback geometry when overlay is not running / bounds unavailable.
_FALLBACK_PANEL_W, _FALLBACK_MARGIN, _FALLBACK_BASE_H = 380, 16, 480


def _hide_friday_ui() -> None:
    """Hide overlay + aim cursor before a grab when configured."""
    if not HIDE_UI_FROM_CAPTURE:
        return
    try:
        from friday.ui.click_marker import hide_aim_cursor
        hide_aim_cursor(wait=True)
    except Exception:
        pass
    if OVERLAY_ENABLED:
        try:
            from friday.ui import overlay
            overlay.hide_for_capture()
        except Exception:
            pass


def _restore_friday_ui() -> None:
    if not HIDE_UI_FROM_CAPTURE:
        return
    if OVERLAY_ENABLED:
        try:
            from friday.ui import overlay
            overlay.show_after_capture()
        except Exception:
            pass


def _mask_ui_region(img: Image.Image, *, mask_overlay: bool) -> Image.Image:
    """Black out Friday UI panels so the VLM ignores our own chrome."""
    from friday.ui.mask import apply_masks

    masked = img
    if mask_overlay and OVERLAY_ENABLED:
        bounds = None
        try:
            from friday.ui import overlay
            bounds = overlay.panel_bounds(img.size[0], img.size[1])
        except Exception:
            bounds = None

        if bounds is None:
            w, h = img.size
            x0 = max(0, w - _FALLBACK_PANEL_W - _FALLBACK_MARGIN - 12)
            y0 = max(0, _FALLBACK_MARGIN - 8)
            # Include approval-mode height (+100) so taller panels never leak.
            x1, y1 = w, min(h, y0 + _FALLBACK_BASE_H + 100 + 32)
            bounds = (x0, y0, x1, y1)

        masked = img.copy()
        ImageDraw.Draw(masked).rectangle(list(bounds), fill=(13, 13, 20))

    return apply_masks(masked)


def _grab_raw_frame(sct, monitor: dict) -> tuple[Image.Image, tuple[int, int]]:
    shot = sct.grab(monitor)
    img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
    native = (monitor["width"], monitor["height"])
    return img, native


def _preprocess_frame(
    img: Image.Image,
    native_size: tuple[int, int],
    *,
    store_pil: bool,
) -> FramePacket:
    from friday.vision.preprocessor import get_preprocessor

    preprocessor = get_preprocessor()
    b64, image_size = preprocessor.prepare_base64(img, target_size=PREPROCESS_TARGET_SIZE)
    return FramePacket(
        base64_png=b64,
        native_size=native_size,
        image_size=image_size,
        pil_image=img if store_pil else None,
    )


def _encode_video_mp4(frames: list[Image.Image], fps: float) -> str | None:
    if len(frames) < 2 or not shutil.which("ffmpeg"):
        return None

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        for i, frame in enumerate(frames):
            frame.convert("RGB").save(tmp_path / f"frame_{i:04d}.jpg", quality=85)

        out = tmp_path / "clip.mp4"
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-framerate", str(fps),
            "-i", str(tmp_path / "frame_%04d.jpg"),
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(out),
        ]
        try:
            subprocess.run(cmd, check=True, timeout=30)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
            return None

        if not out.exists():
            return None
        return base64.b64encode(out.read_bytes()).decode("ascii")


class LiveScreenFeed:
    """Background live screen capture — overlay preview + model buffer."""

    def __init__(self, *, mask_overlay: bool | None = None) -> None:
        buffer_len = max(4, int(STREAM_VIDEO_SECONDS * STREAM_VIDEO_FPS) + 2)
        self._buffer: deque[FramePacket] = deque(maxlen=buffer_len)
        self._lock = threading.Lock()
        self._running = False
        self._grabbing = threading.Event()
        self._grabbing.set()
        self._thread: threading.Thread | None = None
        self._native_size: tuple[int, int] = (0, 0)
        self._frames_pushed = 0
        self._last_gui_emit = 0.0
        self._store_pil = should_store_frame_pil()
        # Only mask the floating overlay region when that overlay is actually used.
        self._mask_overlay = OVERLAY_ENABLED if mask_overlay is None else mask_overlay

    def pause(self) -> None:
        self._grabbing.clear()

    def resume(self) -> None:
        self._grabbing.set()

    @property
    def native_size(self) -> tuple[int, int]:
        return self._native_size

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, name="FridayLiveFeed", daemon=True)
        self._thread.start()
        if self._mask_overlay and OVERLAY_ENABLED:
            from friday.ui import overlay
            overlay.set_live_mode(True)
        print(f"[Live] Feed started ({LIVE_PREVIEW_FPS:.1f} fps preview).")

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
        if self._mask_overlay and OVERLAY_ENABLED:
            from friday.ui import overlay
            overlay.set_live_mode(False)
        print("[Live] Feed stopped.")

    def _maybe_emit_gui_frame(self, clean: Image.Image, frame_num: int) -> None:
        if GUI_LIVE_EMIT_INTERVAL > 0:
            now = time.monotonic()
            if now - self._last_gui_emit < GUI_LIVE_EMIT_INTERVAL:
                return
            self._last_gui_emit = now
        from friday.ui.events import emit
        emit("live_frame", image=clean.copy(), frame_index=frame_num)

    def _capture_clean(self, sct, monitor: dict) -> tuple[Image.Image, tuple[int, int]]:
        _hide_friday_ui()
        try:
            raw, native = _grab_raw_frame(sct, monitor)
        finally:
            _restore_friday_ui()
        clean = _mask_ui_region(raw, mask_overlay=self._mask_overlay)
        return clean, native

    def _run_loop(self) -> None:
        import mss

        interval = 1.0 / max(0.5, LIVE_PREVIEW_FPS)
        with mss.mss() as sct:
            monitor = sct.monitors[PRIMARY_MONITOR_INDEX]
            while self._running:
                if not self._grabbing.wait(timeout=0.05):
                    continue
                t0 = time.perf_counter()
                try:
                    clean, native = self._capture_clean(sct, monitor)
                    self._native_size = native
                    packet = _preprocess_frame(clean, native, store_pil=self._store_pil)
                    with self._lock:
                        self._buffer.append(packet)
                        self._frames_pushed += 1
                        frame_num = self._frames_pushed
                    if self._mask_overlay and OVERLAY_ENABLED:
                        from friday.ui import overlay
                        overlay.update_live_frame(clean, frame_index=frame_num)
                    self._maybe_emit_gui_frame(clean, frame_num)
                except Exception as exc:
                    print(f"[Live] Frame grab error: {exc}")
                elapsed = time.perf_counter() - t0
                time.sleep(max(0.02, interval - elapsed))

    def wait_until_ready(self, timeout: float = 5.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                if self._buffer:
                    return True
            time.sleep(0.05)
        return False

    def frame_serial(self) -> int:
        with self._lock:
            return self._frames_pushed

    def latest_packet(self) -> FramePacket | None:
        with self._lock:
            return self._buffer[-1] if self._buffer else None

    def wait_for_fresh_frame(
        self,
        after_serial: int,
        timeout: float = 1.5,
        *,
        require_fresh: bool = False,
    ) -> FramePacket | None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                if self._frames_pushed > after_serial and self._buffer:
                    return self._buffer[-1]
            time.sleep(0.04)
        if require_fresh:
            return None
        return self.latest_packet()

    def capture_oneshot(self) -> VisionPayload | None:
        """One-shot capture for LIVE_MODE=false or empty buffer recovery."""
        import mss

        try:
            with mss.mss() as sct:
                monitor = sct.monitors[PRIMARY_MONITOR_INDEX]
                clean, native = self._capture_clean(sct, monitor)
            self._native_size = native
            packet = _preprocess_frame(clean, native, store_pil=False)
            with self._lock:
                self._buffer.append(packet)
                self._frames_pushed += 1
            return VisionPayload(
                native_size=native,
                image_size=packet.image_size,
                frame_b64_list=[packet.base64_png],
                is_video=False,
                frame_count=1,
            )
        except Exception as exc:
            print(f"[Live] One-shot capture failed: {exc}")
            return None

    def capture_for_aim_verify(
        self,
        native_x: int,
        native_y: int,
        *,
        state: Literal["aim", "adjust", "confirm"] = "aim",
        label: str = "",
    ) -> FramePacket:
        """Grab a clean frame and composite the aim marker in PIL only (no Win32 layer)."""
        from friday.ui.click_marker import draw_aim_marker_on_image, hide_aim_cursor

        import mss

        # Hide Win32 cursor so mss does not double-draw the marker.
        hide_aim_cursor(wait=True)
        with mss.mss() as sct:
            monitor = sct.monitors[PRIMARY_MONITOR_INDEX]
            clean, native = self._capture_clean(sct, monitor)
        self._native_size = native
        marked = draw_aim_marker_on_image(clean, native_x, native_y, state=state, label=label)
        return _preprocess_frame(marked, native, store_pil=False)

    def snapshot_for_model(self) -> VisionPayload | None:
        with self._lock:
            packets = list(self._buffer)

        if not packets:
            return None

        latest = packets[-1]
        native_size = latest.native_size
        image_size = latest.image_size

        if STREAM_USE_VIDEO:
            clip_count = max(2, int(STREAM_VIDEO_SECONDS * STREAM_VIDEO_FPS))
            clip_packets = packets[-clip_count:]
            raw_frames = [p.pil_image for p in clip_packets if p.pil_image is not None]
            if not raw_frames:
                print("[Live] Video mode needs STORE_FRAME_PIL=true — falling back to still frame.")
            else:
                video_b64 = _encode_video_mp4(raw_frames, STREAM_VIDEO_FPS)
                if video_b64:
                    return VisionPayload(
                        native_size=native_size,
                        image_size=image_size,
                        frame_b64_list=[],
                        video_b64=video_b64,
                        is_video=True,
                        frame_count=len(clip_packets),
                    )

        frame_b64_list = [p.base64_png for p in packets[-max(1, STREAM_FRAME_COUNT):]]
        return VisionPayload(
            native_size=native_size,
            image_size=image_size,
            frame_b64_list=frame_b64_list,
            is_video=False,
            frame_count=len(frame_b64_list),
        )
