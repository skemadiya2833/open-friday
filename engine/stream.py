"""
Continuous live screen feed for overlay preview and VLM video input.

Runs a background thread that grabs frames at LIVE_PREVIEW_FPS, pushes them to
the overlay in real time, and maintains a ring buffer for model inference.
"""

from __future__ import annotations

import base64
import shutil
import subprocess
import tempfile
import threading
import time
from collections import deque
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Literal

from PIL import Image, ImageDraw

from config import (
    LIVE_PREVIEW_FPS,
    OVERLAY_ENABLED,
    PREPROCESS_TARGET_SIZE,
    PRIMARY_MONITOR_INDEX,
    STREAM_FRAME_COUNT,
    STREAM_USE_VIDEO,
    STREAM_VIDEO_FPS,
    STREAM_VIDEO_SECONDS,
)

if OVERLAY_ENABLED:
    from engine import overlay
    from engine.overlay import BASE_H, MARGIN, PANEL_W
else:
    PANEL_W, MARGIN, BASE_H = 440, 16, 660


@dataclass
class FramePacket:
    base64_png: str
    native_size: tuple[int, int]
    image_size: tuple[int, int]
    pil_image: Image.Image


@dataclass
class VisionPayload:
    """What we send to Qwen2.5-VL on each inference tick."""

    native_size: tuple[int, int]
    image_size: tuple[int, int]
    frame_b64_list: list[str]
    video_b64: str | None = None
    is_video: bool = False
    frame_count: int = 0

    @property
    def frame_b64(self) -> str | None:
        return self.frame_b64_list[-1] if self.frame_b64_list else None


def _mask_ui_region(img: Image.Image) -> Image.Image:
    """
    Black out the Friday overlay panel region so grabs never need to hide the
    window (which caused visible flicker at live preview rates).
    """
    w, h = img.size
    x0 = max(0, w - PANEL_W - MARGIN - 12)
    y0 = max(0, MARGIN - 8)
    x1 = w
    y1 = min(h, y0 + BASE_H + 32)
    masked = img.copy()
    ImageDraw.Draw(masked).rectangle([x0, y0, x1, y1], fill=(15, 15, 26))
    return masked


def _grab_raw_frame() -> tuple[Image.Image, tuple[int, int]]:
    import mss

    with mss.mss() as sct:
        monitor = sct.monitors[PRIMARY_MONITOR_INDEX]
        shot = sct.grab(monitor)
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        native = (monitor["width"], monitor["height"])
    return img, native


def _preprocess_frame(img: Image.Image, native_size: tuple[int, int]) -> FramePacket:
    from engine.preprocessor import get_preprocessor

    preprocessor = get_preprocessor()
    b64, image_size = preprocessor.prepare_base64(img, target_size=PREPROCESS_TARGET_SIZE)
    return FramePacket(
        base64_png=b64,
        native_size=native_size,
        image_size=image_size,
        pil_image=img,
    )


def _encode_video_mp4(frames: list[Image.Image], fps: float) -> str | None:
    """Encode frames to base64 MP4 via ffmpeg (if available)."""
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

    def __init__(self) -> None:
        buffer_len = max(4, int(STREAM_VIDEO_SECONDS * STREAM_VIDEO_FPS) + 2)
        self._buffer: deque[FramePacket] = deque(maxlen=buffer_len)
        self._lock = threading.Lock()
        self._running = False
        self._grabbing = threading.Event()
        self._grabbing.set()
        self._thread: threading.Thread | None = None
        self._native_size: tuple[int, int] = (0, 0)
        self._frames_pushed = 0

    def pause(self) -> None:
        """Stop grabbing while the model is thinking (avoids wasted work)."""
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
        if OVERLAY_ENABLED:
            overlay.set_live_mode(True)
        print(f"[Live] Feed started ({LIVE_PREVIEW_FPS:.1f} fps preview).")

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
        if OVERLAY_ENABLED:
            overlay.set_live_mode(False)
        print("[Live] Feed stopped.")

    def _run_loop(self) -> None:
        interval = 1.0 / max(0.5, LIVE_PREVIEW_FPS)
        while self._running:
            if not self._grabbing.wait(timeout=0.05):
                continue

            t0 = time.perf_counter()
            try:
                raw, native = _grab_raw_frame()
                self._native_size = native
                clean = _mask_ui_region(raw)
                packet = _preprocess_frame(clean, native)
                with self._lock:
                    self._buffer.append(packet)
                    self._frames_pushed += 1
                    frame_num = self._frames_pushed
                if OVERLAY_ENABLED:
                    overlay.update_live_frame(clean, frame_index=frame_num)
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
        self, after_serial: int, timeout: float = 1.5,
    ) -> FramePacket | None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                if self._frames_pushed > after_serial and self._buffer:
                    return self._buffer[-1]
            time.sleep(0.04)
        return self.latest_packet()

    def packet_to_vision(self, packet: FramePacket) -> VisionPayload:
        return VisionPayload(
            native_size=packet.native_size,
            image_size=packet.image_size,
            frame_b64_list=[packet.base64_png],
            is_video=False,
            frame_count=1,
        )

    def capture_for_aim_verify(
        self,
        native_x: int,
        native_y: int,
        *,
        state: Literal["aim", "adjust", "confirm"] = "aim",
        label: str = "",
    ) -> FramePacket:
        """Fresh grab with crosshair composited into the image for VLM verification."""
        from engine.click_marker import draw_aim_marker_on_image

        raw, native = _grab_raw_frame()
        self._native_size = native
        clean = _mask_ui_region(raw)
        marked = draw_aim_marker_on_image(clean, native_x, native_y, state=state, label=label)
        return _preprocess_frame(marked, native)

    def snapshot_for_model(self) -> VisionPayload | None:
        """Build vision input from the live buffer (video clip or frame list)."""
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
            raw_frames = [p.pil_image for p in clip_packets]
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


# Back-compat alias
LiveFrameStream = LiveScreenFeed
