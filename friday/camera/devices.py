"""Enumerate connected webcams and persist the owner's selected index."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_prefs_lock = threading.Lock()
_MAX_PROBE = 8


def _prefs_path() -> Path:
    from friday.config import DATA_DIR

    return Path(DATA_DIR) / "camera_prefs.json"


def load_prefs() -> dict[str, Any]:
    path = _prefs_path()
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _write_prefs(update: dict[str, Any]) -> dict[str, Any]:
    path = _prefs_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _prefs_lock:
        data = load_prefs()
        data.update(update)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return dict(data)


def load_selected_index() -> int | None:
    """Owner pick from Systems UI, if any. None → fall back to env."""
    try:
        if "index" not in load_prefs():
            return None
        idx = int(load_prefs().get("index"))
        return max(0, min(idx, 31))
    except Exception:  # noqa: BLE001
        return None


def load_selected_backend() -> str:
    """Preferred OpenCV backend for the selected index (msmf | dshow | '')."""
    try:
        raw = str(load_prefs().get("backend") or "").strip().lower()
        if raw in ("msmf", "dshow", "default"):
            return raw
    except Exception:  # noqa: BLE001
        pass
    return ""


def load_camera_enabled() -> bool | None:
    """Systems UI enable flag. None → fall back to FRIDAY_CAMERA env."""
    prefs = load_prefs()
    if "enabled" not in prefs:
        return None
    return bool(prefs.get("enabled"))


def save_camera_enabled(enabled: bool) -> dict[str, Any]:
    data = _write_prefs({"enabled": bool(enabled)})
    os.environ["FRIDAY_CAMERA"] = "on" if enabled else "off"
    try:
        from friday.safety.audit import get_audit_log

        get_audit_log().record(
            tool="camera_enable",
            args={"enabled": bool(enabled)},
            outcome="ok",
            risk="confirm",
            caller="camera",
            detail=f"enabled={bool(enabled)}",
        )
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "enabled": bool(data.get("enabled"))}


def save_selected_index(index: int, *, backend: str = "") -> dict[str, Any]:
    idx = max(0, min(int(index), 31))
    be = (backend or "").strip().lower()
    if be not in ("msmf", "dshow", "default"):
        be = ""
    path = _prefs_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _prefs_lock:
        data = load_prefs()
        data["index"] = idx
        if be:
            data["backend"] = be
        else:
            data.pop("backend", None)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.environ["FRIDAY_CAMERA_INDEX"] = str(idx)
    try:
        from friday.safety.audit import get_audit_log

        get_audit_log().record(
            tool="camera_select",
            args={"index": idx, "backend": be},
            outcome="ok",
            risk="confirm",
            caller="camera",
            detail=f"index={idx} backend={be or 'auto'}",
        )
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "index": idx, "backend": be}


@dataclass
class CameraDevice:
    index: int
    name: str
    width: int = 0
    height: int = 0
    backend: str = ""
    available: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "name": self.name,
            "width": self.width,
            "height": self.height,
            "backend": self.backend,
            "available": self.available,
            "label": self.label(),
            "key": self.selection_key(),
        }

    def label(self) -> str:
        res = f"{self.width}×{self.height}" if self.width and self.height else ""
        bits = [self.name or f"Camera {self.index}"]
        if res:
            bits.append(res)
        bits.append(f"{self.backend or 'cv'}:{self.index}")
        return " · ".join(bits)

    def selection_key(self) -> str:
        return f"{self.backend or 'default'}:{self.index}"


def _windows_friendly_names() -> list[str]:
    """Best-effort PnP camera names (order may not match OpenCV indices)."""
    if sys.platform != "win32":
        return []
    ps = (
        "Get-CimInstance Win32_PnPEntity | "
        "Where-Object { $_.PNPClass -eq 'Camera' -or $_.PNPClass -eq 'Image' "
        "-or $_.Name -match 'Camera|Webcam|USB Video' } | "
        "Select-Object -ExpandProperty Name"
    )
    try:
        out = subprocess.run(  # noqa: S603
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        names = [ln.strip() for ln in (out.stdout or "").splitlines() if ln.strip()]
        # De-dupe preserving order
        seen: set[str] = set()
        uniq: list[str] = []
        for n in names:
            if n.lower() in seen:
                continue
            seen.add(n.lower())
            uniq.append(n)
        return uniq
    except Exception:  # noqa: BLE001
        return []


def _silence_opencv_logs() -> Any:
    """Quiet VIDEOIO spam while probing indices (restored by caller)."""
    try:
        import cv2

        prev = cv2.getLogLevel() if hasattr(cv2, "getLogLevel") else None
        if hasattr(cv2, "setLogLevel"):
            cv2.setLogLevel(0)  # SILENT
        elif hasattr(cv2, "utils") and hasattr(cv2.utils, "logging"):
            cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_SILENT)
        return prev
    except Exception:  # noqa: BLE001
        return None


def _restore_opencv_logs(prev: Any) -> None:
    try:
        import cv2

        if prev is not None and hasattr(cv2, "setLogLevel"):
            cv2.setLogLevel(prev)
    except Exception:  # noqa: BLE001
        pass


def _backend_apis() -> list[tuple[str, int | None]]:
    """Windows MSMF and DSHOW use different index maps — probe both separately."""
    import cv2

    if sys.platform == "win32":
        out: list[tuple[str, int | None]] = []
        if hasattr(cv2, "CAP_MSMF"):
            out.append(("msmf", cv2.CAP_MSMF))
        if hasattr(cv2, "CAP_DSHOW"):
            out.append(("dshow", cv2.CAP_DSHOW))
        return out or [("default", None)]
    return [("default", None)]


def _open_capture(index: int, preferred: str | None = None):
    """Open a camera index. Prefer the Systems-selected backend (MSMF/DSHOW indices differ)."""
    backends = _backend_apis()
    pref = (preferred or "").strip().lower()
    if pref:
        backends = sorted(backends, key=lambda b: 0 if b[0] == pref else 1)

    for name, api in backends:
        cap = None
        try:
            import cv2

            cap = cv2.VideoCapture(index, api) if api is not None else cv2.VideoCapture(index)
            if cap is not None and cap.isOpened():
                return cap, name
        except Exception:  # noqa: BLE001
            pass
        if cap is not None:
            try:
                cap.release()
            except Exception:  # noqa: BLE001
                pass
    return None, ""


def _probe_backend(backend: str, api: int | None, *, limit: int, friendly: list[str]) -> list[CameraDevice]:
    import cv2

    found: list[CameraDevice] = []
    misses = 0
    for i in range(limit):
        cap = None
        try:
            cap = cv2.VideoCapture(i, api) if api is not None else cv2.VideoCapture(i)
            if cap is None or not cap.isOpened():
                misses += 1
                if misses >= 2:
                    break
                continue
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
            ok, frame = cap.read()
            if not ok or frame is None:
                misses += 1
                if misses >= 2:
                    break
                continue
            misses = 0
            if not w or not h:
                h, w = int(frame.shape[0]), int(frame.shape[1])
            # Match PnP names by probe order within this backend (best-effort).
            name = (
                friendly[len(found)]
                if len(found) < len(friendly)
                else (friendly[i] if i < len(friendly) else f"Camera {i}")
            )
            found.append(
                CameraDevice(
                    index=i,
                    name=name,
                    width=w,
                    height=h,
                    backend=backend,
                    available=True,
                )
            )
        except Exception:  # noqa: BLE001
            misses += 1
            if misses >= 2:
                break
        finally:
            if cap is not None:
                try:
                    cap.release()
                except Exception:  # noqa: BLE001
                    pass
    return found


def list_cameras(*, max_index: int = _MAX_PROBE) -> list[CameraDevice]:
    """Probe OpenCV indices per backend. Does not keep devices open.

    On Windows, MSMF and DirectShow assign different indices to the same hardware —
    we list both so the Systems picker (and capture) can bind the right one.
    """
    from friday.camera.capture import opencv_available

    if not opencv_available():
        return []

    try:
        import cv2  # noqa: F401
    except Exception:  # noqa: BLE001
        return []

    friendly = _windows_friendly_names()
    # Probe a few more slots than PnP names — virtual cams often lack PnP Camera class.
    soft_cap = max(len(friendly) + 2, 5)
    limit = max(1, min(int(max_index), soft_cap, _MAX_PROBE))

    found: list[CameraDevice] = []
    seen: set[tuple[str, int]] = set()
    prev_log = _silence_opencv_logs()
    try:
        for backend, api in _backend_apis():
            for dev in _probe_backend(backend, api, limit=limit, friendly=friendly):
                key = (dev.backend, dev.index)
                if key in seen:
                    continue
                seen.add(key)
                found.append(dev)
    finally:
        _restore_opencv_logs(prev_log)

    # Stable order: backend then index (msmf before dshow so physical cams surface first).
    order = {"msmf": 0, "dshow": 1, "default": 2}
    found.sort(key=lambda d: (order.get(d.backend, 9), d.index))
    return found


def devices_payload() -> dict[str, Any]:
    from friday.camera.capture import opencv_available
    from friday.camera.session import camera_backend, camera_feature_enabled, camera_index

    devices = list_cameras()
    selected = camera_index()
    backend = camera_backend()
    pnp = _windows_friendly_names()
    return {
        "ok": True,
        "enabled": camera_feature_enabled(),
        "opencv": opencv_available(),
        "selected_index": selected,
        "selected_backend": backend,
        "selected_key": f"{backend}:{selected}" if backend else str(selected),
        "devices": [d.to_dict() for d in devices],
        "count": len(devices),
        "pnp_names": pnp,
    }
