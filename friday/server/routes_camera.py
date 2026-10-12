"""Owner-controlled webcam API — arm/disarm/snap. Frames never logged."""

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


@router.get("/api/camera/status")
def camera_status() -> dict[str, Any]:
    from friday.camera.session import get_camera_session

    return get_camera_session().status().to_dict()


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


@router.post("/api/camera/snap")
def camera_snap(body: SnapBody | None = None) -> dict[str, Any]:
    """Owner-initiated one-shot describe. Requires feature on + armed. No frame in response."""
    from friday.camera.capture import capture_jpeg_b64
    from friday.camera.describe import describe_camera
    from friday.camera.session import camera_feature_enabled, get_camera_session

    body = body or SnapBody()
    if not camera_feature_enabled():
        raise HTTPException(status_code=400, detail="FRIDAY_CAMERA is off")
    session = get_camera_session()
    if not session.is_armed():
        raise HTTPException(status_code=403, detail="Camera not armed")

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
