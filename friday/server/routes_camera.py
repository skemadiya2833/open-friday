"""Owner-controlled webcam API — arm/disarm/snap/list/select. Frames never logged."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(tags=["camera"])


class ArmBody(BaseModel):
    ttl_seconds: float | None = Field(default=None, ge=30, le=3600)


class SnapBody(BaseModel):
    question: str = Field(
        default="What do you see in front of the camera?",
        max_length=500,
    )


class SelectBody(BaseModel):
    index: int = Field(ge=0, le=31)
    backend: str = Field(default="", max_length=16)
    name: str = Field(default="", max_length=120)
    resolution: str | None = Field(default=None, max_length=16)


class EnableBody(BaseModel):
    enabled: bool


@router.get("/api/camera/status")
def camera_status() -> dict[str, Any]:
    from friday.camera.session import get_camera_session

    return get_camera_session().status().to_dict()


@router.get("/api/camera/devices")
def camera_devices(deep: bool = False) -> dict[str, Any]:
    """List connected cameras.

    Default: DirectShow *names* only (no open). ``deep=1`` (Scan) opens the
    selected device once for resolution — never walks every virtual cam.
    """
    from friday.camera.capture import opencv_available
    from friday.camera.devices import devices_payload

    if not opencv_available():
        return {
            "ok": False,
            "opencv": False,
            "devices": [],
            "count": 0,
            "selected_index": 0,
            "error": "OpenCV missing — pip install -r requirements/camera.lock.txt",
        }
    return devices_payload(deep=bool(deep))


@router.post("/api/camera/select")
def camera_select(body: SelectBody) -> dict[str, Any]:
    """Persist the Systems UI camera choice (overrides FRIDAY_CAMERA_INDEX)."""
    from friday.camera.devices import save_selected_index
    from friday.camera.session import get_camera_session

    out = save_selected_index(
        body.index,
        backend=(body.backend or "").strip(),
        name=(body.name or "").strip(),
        resolution=body.resolution,
    )
    st = get_camera_session().status().to_dict()
    return {**out, "status": st}


@router.post("/api/camera/enable")
def camera_enable(body: EnableBody) -> dict[str, Any]:
    """Systems toggle — no .env edit required. Disabling also disarms."""
    from friday.camera.devices import save_camera_enabled
    from friday.camera.session import get_camera_session

    out = save_camera_enabled(body.enabled)
    session = get_camera_session()
    if not body.enabled:
        session.disarm(reason="disabled_in_settings")
    return {**out, "status": session.status().to_dict()}


@router.post("/api/camera/arm")
def camera_arm(body: ArmBody | None = None) -> dict[str, Any]:
    from friday.camera.session import get_camera_session

    body = body or ArmBody()
    out = get_camera_session().arm(ttl=body.ttl_seconds)
    if not out.get("ok"):
        raise HTTPException(status_code=400, detail=out.get("error") or "cannot arm")
    return out


@router.post("/api/camera/disarm")
def camera_disarm() -> dict[str, Any]:
    from friday.camera.session import get_camera_session

    return get_camera_session().disarm(reason="api")


def _ensure_armed_for_look(session) -> None:
    """Arm briefly for preview/snap so Systems buttons just work (must be enabled)."""
    from friday.camera.session import camera_feature_enabled

    if not camera_feature_enabled():
        raise HTTPException(
            status_code=400,
            detail="Camera is off — turn on Enable camera in Systems first.",
        )
    if session.is_armed():
        return
    out = session.arm(ttl=120)
    if not out.get("ok") or not session.is_armed():
        # 400 not 403 — this is a settings/state issue, not an auth denial.
        raise HTTPException(
            status_code=400,
            detail=out.get("error") or "Could not arm the camera.",
        )


@router.get("/api/camera/preview")
def camera_preview():
    """JPEG snapshot for Systems / phone. Auto-arms briefly when enabled."""
    from fastapi.responses import Response

    from friday.camera.capture import capture_jpeg_b64
    from friday.camera.session import get_camera_session

    session = get_camera_session()
    _ensure_armed_for_look(session)
    shot = capture_jpeg_b64()
    if not shot.ok or not shot.jpeg_b64:
        raise HTTPException(status_code=503, detail=shot.error or "capture failed")
    import base64

    raw = base64.b64decode(shot.jpeg_b64)
    try:
        from friday.safety.audit import get_audit_log

        get_audit_log().record(
            tool="camera_preview",
            args={"width": shot.width, "height": shot.height, "bytes": len(raw)},
            outcome="ok",
            risk="confirm",
            caller="api",
            detail=f"duration_ms={shot.duration_ms}",
        )
    except Exception:  # noqa: BLE001
        pass
    return Response(content=raw, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.post("/api/camera/snap")
def camera_snap(body: SnapBody | None = None) -> dict[str, Any]:
    """Owner-initiated one-shot describe. Auto-arms briefly when enabled."""
    from friday.camera.capture import capture_jpeg_b64
    from friday.camera.describe import describe_camera
    from friday.camera.session import get_camera_session

    body = body or SnapBody()
    session = get_camera_session()
    _ensure_armed_for_look(session)

    shot = capture_jpeg_b64()
    if not shot.ok or not shot.jpeg_b64:
        raise HTTPException(status_code=503, detail=shot.error or "capture failed")

    try:
        from friday.safety.audit import get_audit_log

        get_audit_log().record(
            tool="camera_snap",
            args={"width": shot.width, "height": shot.height, "bytes": shot.bytes_len},
            outcome="ok",
            risk="confirm",
            caller="api",
            detail=f"duration_ms={shot.duration_ms}",
        )
    except Exception:  # noqa: BLE001
        pass

    reply = describe_camera(body.question, frame_b64=shot.jpeg_b64)
    meta = shot.to_dict()
    del shot
    return {"ok": True, "reply": reply, "capture": meta}
