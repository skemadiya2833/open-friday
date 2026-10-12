"""Owner arm-grant for the webcam. Capture is forbidden unless armed."""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import Any


def camera_feature_enabled() -> bool:
    """Systems UI prefs override ``FRIDAY_CAMERA`` so owners are not stuck on .env."""
    try:
        from friday.camera.devices import load_camera_enabled

        picked = load_camera_enabled()
        if picked is not None:
            return bool(picked)
    except Exception:  # noqa: BLE001
        pass
    return os.getenv("FRIDAY_CAMERA", "off").strip().lower() in ("1", "true", "yes", "on")


def camera_index() -> int:
    """Active capture index: Systems UI prefs override ``FRIDAY_CAMERA_INDEX``."""
    try:
        from friday.camera.devices import load_selected_index

        picked = load_selected_index()
        if picked is not None:
            return picked
    except Exception:  # noqa: BLE001
        pass
    try:
        return max(0, int(os.getenv("FRIDAY_CAMERA_INDEX", "0") or "0"))
    except ValueError:
        return 0


def camera_backend() -> str:
    """Preferred OpenCV backend from Systems UI (msmf | dshow | '')."""
    try:
        from friday.camera.devices import load_selected_backend

        return load_selected_backend()
    except Exception:  # noqa: BLE001
        return ""


def arm_ttl_seconds() -> float:
    try:
        return max(30.0, float(os.getenv("FRIDAY_CAMERA_ARM_TTL", "300") or "300"))
    except ValueError:
        return 300.0


@dataclass
class CameraStatus:
    enabled: bool
    armed: bool
    live: bool
    index: int
    opencv: bool
    arm_expires_in: float | None
    detail: str = ""
    index_label: str = ""
    backend: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "armed": self.armed,
            "live": self.live,
            "index": self.index,
            "backend": self.backend or "",
            "index_label": self.index_label or f"Camera {self.index}",
            "opencv": self.opencv,
            "arm_expires_in": self.arm_expires_in,
            "detail": self.detail,
        }


class CameraSession:
    """Thread-safe arm grant + live flag. Never holds the device across turns."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._armed_until = 0.0
        self._live = False

    def arm(self, ttl: float | None = None) -> dict[str, Any]:
        if not camera_feature_enabled():
            return {
                "ok": False,
                "error": "Camera is off — enable it in Systems → Camera, then Arm.",
            }
        ttl_s = float(ttl) if ttl is not None else arm_ttl_seconds()
        ttl_s = max(30.0, min(ttl_s, 3600.0))
        with self._lock:
            self._armed_until = time.time() + ttl_s
        self._audit("camera_arm", detail=f"ttl={ttl_s}")
        return {"ok": True, "armed": True, "ttl_seconds": ttl_s, **self.status().to_dict()}

    def disarm(self, *, reason: str = "owner") -> dict[str, Any]:
        with self._lock:
            self._armed_until = 0.0
            self._live = False
        self._audit("camera_disarm", detail=reason)
        return {"ok": True, "armed": False, "reason": reason, **self.status().to_dict()}

    def is_armed(self) -> bool:
        with self._lock:
            return camera_feature_enabled() and time.time() < self._armed_until

    def set_live(self, live: bool) -> None:
        with self._lock:
            self._live = bool(live)

    def is_live(self) -> bool:
        with self._lock:
            return self._live

    def status(self) -> CameraStatus:
        from friday.camera.capture import opencv_available

        with self._lock:
            remaining = max(0.0, self._armed_until - time.time()) if self._armed_until else 0.0
            enabled = camera_feature_enabled()
            armed = enabled and remaining > 0
            idx = camera_index()
            be = camera_backend()
            label = f"Camera {idx}" + (f" · {be}" if be else "")
            if not enabled:
                detail = "disabled — turn on Enable camera in Systems"
            elif not opencv_available():
                detail = "opencv missing — pip install -r requirements/camera.lock.txt"
            elif not armed:
                detail = "disarmed — Arm before using the camera"
            else:
                detail = f"armed for {int(remaining)}s · {label}"
            return CameraStatus(
                enabled=enabled,
                armed=armed,
                live=self._live,
                index=idx,
                backend=be,
                index_label=label,
                opencv=opencv_available(),
                arm_expires_in=round(remaining, 1) if armed else None,
                detail=detail,
            )

    @staticmethod
    def _audit(tool: str, *, detail: str = "") -> None:
        try:
            from friday.safety.audit import get_audit_log

            get_audit_log().record(
                tool=tool,
                args={},
                outcome="ok",
                risk="confirm",
                caller="camera",
                detail=detail[:200],
            )
        except Exception:  # noqa: BLE001
            pass


_session: CameraSession | None = None
_session_lock = threading.Lock()


def get_camera_session() -> CameraSession:
    global _session
    with _session_lock:
        if _session is None:
            _session = CameraSession()
        return _session


def reset_camera_session_for_tests() -> None:
    global _session
    with _session_lock:
        _session = CameraSession()
