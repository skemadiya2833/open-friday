"""Enumerate connected webcams and persist the owner's selected device + resolution.

Windows note: OpenCV MSMF/DSHOW indices are *not* interchangeable, and PnP name
order does **not** match OpenCV probe order (that bug made \"SNAP U2\" open Snap Camera).
We label DSHOW devices by fingerprint-matching ffmpeg's DirectShow name list when available.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_prefs_lock = threading.Lock()
_MAX_PROBE = 8

# Virtual / software cameras — deprioritize for desk look defaults.
_VIRTUAL_HINTS = (
    "snap camera",
    "obs virtual",
    "obs-camera",
    "manycam",
    "nvidia broadcast",
    "nvidia",
    "vcamds",
    "nvx",
    "maxine",
    "xsplit",
    "iriun",
    "epoccam",
    "droidcam",
    "unity capture",
    "ndi",
    "virtual camera",
    "virtual cam",
)

# Systems UI resolution presets. "auto" = driver default.
RESOLUTION_PRESETS: dict[str, tuple[int, int]] = {
    "auto": (0, 0),
    "480p": (640, 480),
    "720p": (1280, 720),
    "1080p": (1920, 1080),
}
DEFAULT_RESOLUTION = "720p"


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


def load_resolution() -> str:
    raw = str(load_prefs().get("resolution") or DEFAULT_RESOLUTION).strip().lower()
    return raw if raw in RESOLUTION_PRESETS else DEFAULT_RESOLUTION


def load_resolution_wh() -> tuple[int, int]:
    return RESOLUTION_PRESETS.get(
        load_resolution(), RESOLUTION_PRESETS[DEFAULT_RESOLUTION]
    )


def load_selected_name() -> str:
    """Clean DirectShow device name from prefs (used for ffmpeg capture)."""
    import re

    raw = str(load_prefs().get("name") or "").strip()
    if " · " in raw:
        raw = raw.split(" · ", 1)[0].strip()
    if re.fullmatch(r"Camera\s+\d+", raw, re.IGNORECASE):
        return ""
    return raw[:120]


def clean_device_name(name: str) -> str:
    """Strip UI label decorations down to the device name."""
    import re

    raw = (name or "").strip()
    if " · " in raw:
        raw = raw.split(" · ", 1)[0].strip()
    raw = re.sub(r"\s+", " ", raw).strip()
    if re.fullmatch(r"Camera\s+\d+", raw, re.IGNORECASE):
        return ""
    return raw[:120]


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


def save_selected_index(
    index: int,
    *,
    backend: str = "",
    name: str = "",
    resolution: str | None = None,
) -> dict[str, Any]:
    idx = max(0, min(int(index), 31))
    be = (backend or "").strip().lower()
    if be not in ("msmf", "dshow", "default"):
        be = ""
    label = clean_device_name(name) or (name or "").strip()[:120]
    # Never persist a virtual cam as the desk default when a better name was intended.
    path = _prefs_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _prefs_lock:
        data = load_prefs()
        data["index"] = idx
        if be:
            data["backend"] = be
        else:
            data.pop("backend", None)
        if label:
            data["name"] = label
        if resolution is not None:
            res = str(resolution).strip().lower()
            data["resolution"] = (
                res if res in RESOLUTION_PRESETS else DEFAULT_RESOLUTION
            )
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.environ["FRIDAY_CAMERA_INDEX"] = str(idx)
    # New pick → drop name-list cache so the next panel refresh rebinds.
    _list_cache["at"] = 0.0
    _list_cache["devices"] = None
    try:
        from friday.safety.audit import get_audit_log

        get_audit_log().record(
            tool="camera_select",
            args={"index": idx, "backend": be, "resolution": data.get("resolution")},
            outcome="ok",
            risk="confirm",
            caller="camera",
            detail=f"index={idx} backend={be or 'auto'} name={label[:40]}",
        )
    except Exception:  # noqa: BLE001
        pass
    return {
        "ok": True,
        "index": idx,
        "backend": be,
        "name": label,
        "resolution": data.get("resolution") or DEFAULT_RESOLUTION,
    }


def is_virtual_name(name: str) -> bool:
    n = (name or "").strip().lower()
    return any(h in n for h in _VIRTUAL_HINTS)


@dataclass
class CameraDevice:
    index: int
    name: str
    width: int = 0
    height: int = 0
    backend: str = ""
    available: bool = True
    virtual: bool = False
    mean_luma: float = 0.0
    named_via: str = ""  # ffmpeg | generic

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "name": self.name,
            "width": self.width,
            "height": self.height,
            "backend": self.backend,
            "available": self.available,
            "virtual": self.virtual,
            "label": self.label(),
            "key": self.selection_key(),
            "named_via": self.named_via,
        }

    def label(self) -> str:
        res = f"{self.width}×{self.height}" if self.width and self.height else ""
        bits = [self.name or f"Camera {self.index}"]
        if self.virtual:
            bits.append("virtual")
        if res:
            bits.append(res)
        bits.append(f"{self.backend or 'cv'}:{self.index}")
        return " · ".join(bits)

    def selection_key(self) -> str:
        return f"{self.backend or 'default'}:{self.index}"

    def sort_key(self) -> tuple:
        # Physical first, higher res first, then index.
        return (
            1 if self.virtual else 0,
            -(self.width * self.height),
            self.backend,
            self.index,
        )


def _windows_friendly_names() -> list[str]:
    """Best-effort PnP camera names (order may NOT match OpenCV — do not map by index)."""
    if sys.platform != "win32":
        return []
    ps = (
        "Get-CimInstance Win32_PnPEntity | "
        "Where-Object { $_.PNPClass -eq 'Camera' -or $_.PNPClass -eq 'Image' "
        "-or $_.Name -match 'Camera|Webcam|USB Video' } | "
        "Select-Object -ExpandProperty Name"
    )
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        names = [ln.strip() for ln in (out.stdout or "").splitlines() if ln.strip()]
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


def _ffmpeg_dshow_names() -> list[str]:
    """DirectShow video device names via ffmpeg (order ≠ OpenCV — match by fingerprint)."""
    ff = shutil.which("ffmpeg")
    if not ff or sys.platform != "win32":
        return []
    try:
        proc = subprocess.run(
            [ff, "-hide_banner", "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
            capture_output=True,
            text=True,
            timeout=12,
            check=False,
        )
        err = proc.stderr or ""
        names: list[str] = []
        for ln in err.splitlines():
            # [in#0 @ ...] "SNAP U2" (video)
            m = re.search(r'"([^"]+)"\s*\(video\)', ln, re.IGNORECASE)
            if m:
                names.append(m.group(1).strip())
        return names
    except Exception:  # noqa: BLE001
        return []


def _fingerprint(frame: Any) -> tuple[int, int, int]:
    h, w = int(frame.shape[0]), int(frame.shape[1])
    mean = int(round(float(frame.mean())))
    return w, h, mean


def _ffmpeg_fingerprint(name: str) -> tuple[int, int, int] | None:
    ff = shutil.which("ffmpeg")
    if not ff:
        return None
    try:
        import cv2
    except Exception:  # noqa: BLE001
        return None
    tmp: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            tmp = Path(f.name)
        # video=<name> — quotes handled by list argv (no shell).
        proc = subprocess.run(
            [
                ff,
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "dshow",
                "-i",
                f"video={name}",
                "-frames:v",
                "1",
                "-y",
                str(tmp),
            ],
            capture_output=True,
            timeout=15,
            check=False,
        )
        if proc.returncode != 0 or not tmp.is_file() or tmp.stat().st_size < 100:
            return None
        img = cv2.imread(str(tmp))
        if img is None:
            return None
        return _fingerprint(img)
    except Exception:  # noqa: BLE001
        return None
    finally:
        if tmp is not None:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:  # noqa: BLE001
                pass


def _match_ffmpeg_names(devices: list[CameraDevice]) -> None:
    """Attach real DirectShow names to OpenCV dshow indices.

    OpenCV and ffmpeg often disagree on *default resolution* for the same device, so we
    match on mean luma (stable across stacks) with a greedy 1:1 assignment — not WxH.
    """
    names = _ffmpeg_dshow_names()
    if not names:
        return
    dshow_devs = [d for d in devices if d.backend == "dshow"]
    if not dshow_devs:
        return

    name_means: list[tuple[str, int]] = []
    for name in names:
        fp = _ffmpeg_fingerprint(name)
        if fp:
            name_means.append((name, int(fp[2])))
    if not name_means:
        return

    # All candidate pairs sorted by |Δmean|, assign uniquely.
    pairs: list[tuple[int, CameraDevice, str]] = []
    for d in dshow_devs:
        d_mean = int(round(d.mean_luma))
        for name, mean in name_means:
            pairs.append((abs(d_mean - mean), d, name))
    pairs.sort(key=lambda p: p[0])

    used_dev: set[tuple[str, int]] = set()
    used_name: set[str] = set()
    for dist, d, name in pairs:
        if dist > 20:
            break
        key = (d.backend, d.index)
        if key in used_dev or name in used_name:
            continue
        d.name = name
        d.named_via = "ffmpeg"
        d.virtual = is_virtual_name(name)
        used_dev.add(key)
        used_name.add(name)


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
    """Open a camera index. When preferred is msmf/dshow, do **not** fall across backends."""
    backends = _backend_apis()
    pref = (preferred or "").strip().lower()
    if pref in ("msmf", "dshow"):
        only = [b for b in backends if b[0] == pref]
        backends = only or backends
    elif pref:
        backends = sorted(backends, key=lambda b: 0 if b[0] == pref else 1)

    for name, api in backends:
        cap = None
        try:
            import cv2

            cap = (
                cv2.VideoCapture(index, api)
                if api is not None
                else cv2.VideoCapture(index)
            )
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


def apply_capture_resolution(cap: Any, *, width: int = 0, height: int = 0) -> None:
    """Request a frame size on an open capture (best-effort; drivers may ignore)."""
    if not width or not height:
        return
    try:
        import cv2

        cap.set(cv2.CAP_PROP_FRAME_WIDTH, float(width))
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, float(height))
    except Exception:  # noqa: BLE001
        pass


def _probe_backend(backend: str, api: int | None, *, limit: int) -> list[CameraDevice]:
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
            mean = float(frame.mean())
            # Honest generic name until ffmpeg fingerprinting renames DSHOW devices.
            name = f"Camera {i}"
            found.append(
                CameraDevice(
                    index=i,
                    name=name,
                    width=w,
                    height=h,
                    backend=backend,
                    available=True,
                    virtual=False,
                    mean_luma=mean,
                    named_via="generic",
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


def _list_cameras_ffmpeg_first(*, deep: bool = False) -> list[CameraDevice] | None:
    """Windows: DirectShow *names* are authoritative.

    Default (deep=False): name list only — never open devices (avoids NVIDIA VCAMDS /
    virtual-cam spam when Systems opens the Camera panel).

    deep=True (Scan): open **only the currently selected** device once for WxH / luma.
    Capture always uses the saved name via ffmpeg — never walks every index.
    """
    names = _ffmpeg_dshow_names()
    if not names:
        return None

    selected = load_selected_name().strip().lower()
    devices: list[CameraDevice] = []
    for i, name in enumerate(names):
        w = h = 0
        mean = 0.0
        if deep and selected and name.strip().lower() == selected:
            fp = _ffmpeg_fingerprint(name)
            if fp:
                w, h, mean_i = fp
                mean = float(mean_i)
        devices.append(
            CameraDevice(
                index=i,
                name=name,
                width=w,
                height=h,
                backend="dshow",
                available=True,
                virtual=is_virtual_name(name),
                mean_luma=mean,
                named_via="ffmpeg",
            )
        )
    devices.sort(key=lambda d: d.sort_key())
    return devices


_list_cache: dict[str, Any] = {"at": 0.0, "deep": False, "devices": None}
_LIST_CACHE_TTL_S = 20.0


def list_cameras(*, max_index: int = _MAX_PROBE, deep: bool = False) -> list[CameraDevice]:
    """List cameras. On Windows prefer ffmpeg DirectShow names (stable) over OpenCV indices."""
    import time as _time

    from friday.camera.capture import opencv_available

    now = _time.monotonic()
    cached = _list_cache.get("devices")
    if (
        cached is not None
        and not deep
        and (now - float(_list_cache.get("at") or 0)) < _LIST_CACHE_TTL_S
    ):
        return list(cached)

    try:
        named = _list_cameras_ffmpeg_first(deep=deep)
        if named:
            if not deep:
                _list_cache["at"] = now
                _list_cache["deep"] = False
                _list_cache["devices"] = list(named)
            return named
    except Exception:  # noqa: BLE001
        pass

    if not opencv_available():
        return []

    try:
        import cv2  # noqa: F401
    except Exception:  # noqa: BLE001
        return []

    # Fallback only when ffmpeg DirectShow listing is unavailable.
    # Still avoid deep multi-backend walks unless the owner hit Scan.
    limit = max(1, min(int(max_index), _MAX_PROBE if deep else 2))
    found: list[CameraDevice] = []
    seen: set[tuple[str, int]] = set()
    prev_log = _silence_opencv_logs()
    try:
        backends = _backend_apis()
        # Prefer dshow on Windows; probing msmf+dshow doubles virtual-cam chatter.
        if not deep and any(b[0] == "dshow" for b in backends):
            backends = [b for b in backends if b[0] == "dshow"]
        for backend, api in backends:
            for dev in _probe_backend(backend, api, limit=limit):
                key = (dev.backend, dev.index)
                if key in seen:
                    continue
                seen.add(key)
                found.append(dev)
                if not deep and found:
                    break
            if not deep and found:
                break
    finally:
        _restore_opencv_logs(prev_log)

    if deep:
        try:
            _match_ffmpeg_names(found)
        except Exception:  # noqa: BLE001
            pass

    for d in found:
        if not d.virtual:
            d.virtual = is_virtual_name(d.name)

    found.sort(key=lambda d: d.sort_key())
    if not deep:
        _list_cache["at"] = now
        _list_cache["devices"] = list(found)
    return found


def pick_default_device(devices: list[CameraDevice]) -> CameraDevice | None:
    """Best desk-look default: physical cam with a live picture (not black / virtual)."""
    physical = [d for d in devices if not d.virtual and d.mean_luma > 5]
    pool = physical or [d for d in devices if not d.virtual] or devices
    if not pool:
        return None

    # Prefer names that look like USB webcams over anonymous "Camera N".
    def score(d: CameraDevice) -> tuple:
        named = (
            1
            if d.named_via == "ffmpeg" and not d.name.lower().startswith("camera ")
            else 0
        )
        return (named, d.mean_luma, d.width * d.height)

    return max(pool, key=score)


def devices_payload(*, deep: bool = False) -> dict[str, Any]:
    from friday.camera.capture import opencv_available
    from friday.camera.session import (
        camera_backend,
        camera_feature_enabled,
        camera_index,
    )

    devices = list_cameras(deep=deep)
    selected = camera_index()
    backend = camera_backend()
    saved_name = load_selected_name()
    recommended = pick_default_device(devices)

    # Name wins over stale OpenCV index (fixes Snap Camera ↔ SNAP U2 mixups).
    selected_dev = None
    if saved_name:
        for d in devices:
            if d.name.lower() == saved_name.lower():
                selected_dev = d
                if d.index != selected or (backend and d.backend != backend):
                    save_selected_index(
                        d.index,
                        backend=d.backend,
                        name=d.name,
                        resolution=load_resolution(),
                    )
                    selected = d.index
                    backend = d.backend
                break
    if selected_dev is None:
        selected_dev = next(
            (
                d
                for d in devices
                if d.index == selected and (not backend or d.backend == backend)
            ),
            None,
        )

    warn = ""
    if (
        selected_dev
        and selected_dev.virtual
        and recommended
        and not recommended.virtual
    ):
        warn = (
            f"Selected device looks virtual ({selected_dev.name}). "
            f"Recommended desk camera: {recommended.label()}"
        )
    elif (
        saved_name
        and is_virtual_name(saved_name)
        and recommended
        and not recommended.virtual
    ):
        warn = (
            f"Saved camera '{saved_name}' is virtual. "
            f"Recommended: {recommended.label()}"
        )
    return {
        "ok": True,
        "enabled": camera_feature_enabled(),
        "opencv": opencv_available(),
        "selected_index": selected,
        "selected_backend": backend,
        "selected_key": (
            selected_dev.selection_key()
            if selected_dev
            else (f"{backend}:{selected}" if backend else str(selected))
        ),
        "selected_name": saved_name or (selected_dev.name if selected_dev else ""),
        "capture_by": "ffmpeg-name" if saved_name else "opencv-index",
        "resolution": load_resolution(),
        "resolution_presets": [
            {"id": "auto", "label": "Auto (driver default)"},
            {"id": "480p", "label": "480p · 640×480"},
            {"id": "720p", "label": "720p · 1280×720 (default)"},
            {"id": "1080p", "label": "1080p · 1920×1080"},
        ],
        "recommended_key": recommended.selection_key() if recommended else "",
        "recommended_label": recommended.label() if recommended else "",
        "warning": warn,
        "devices": [d.to_dict() for d in devices],
        "count": len(devices),
        "deep": bool(deep),
        # PnP names are expensive (PowerShell) — only on explicit Scan.
        "pnp_names": _windows_friendly_names() if deep else [],
    }
