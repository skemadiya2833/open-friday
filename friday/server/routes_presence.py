"""Presence skins, portraits, avatar status."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

router = APIRouter(tags=["presence"])


@router.get("/api/presence")
def presence_get() -> dict[str, Any]:
    from friday.avatar.pipeline import avatar_status
    from friday.presence.registry import presence_snapshot

    snap = presence_snapshot()
    snap["avatar"] = avatar_status()
    return snap


class SkinBody(BaseModel):
    skin_id: str = Field(..., min_length=2, max_length=32)


@router.post("/api/presence/skin")
def presence_set_skin(body: SkinBody) -> dict[str, Any]:
    from friday.presence.registry import apply_skin
    from friday.presence.skins import SKINS

    sid = body.skin_id.strip().lower()
    if sid not in SKINS:
        raise HTTPException(400, f"Unknown skin: {sid}")
    return apply_skin(sid)


@router.get("/api/presence/portrait/{skin_id}")
def presence_portrait(skin_id: str):
    from friday.presence.registry import portrait_path_for
    from friday.presence.skins import SKINS

    sid = skin_id.strip().lower()
    if sid not in SKINS:
        raise HTTPException(404, "Unknown skin")
    path = portrait_path_for(sid)
    if not path.is_file():
        raise HTTPException(404, "No portrait uploaded")
    media = "image/png"
    if path.suffix.lower() in {".jpg", ".jpeg"}:
        media = "image/jpeg"
    elif path.suffix.lower() == ".webp":
        media = "image/webp"
    return FileResponse(path, media_type=media)


@router.post("/api/presence/portrait/{skin_id}")
async def presence_upload_portrait(
    skin_id: str, file: UploadFile = File(...)
) -> dict[str, Any]:
    from friday.config import DATA_DIR
    from friday.presence.skins import SKINS

    sid = skin_id.strip().lower()
    if sid not in SKINS:
        raise HTTPException(400, f"Unknown skin: {sid}")
    name = (file.filename or "portrait.png").lower()
    ext = ".png"
    if name.endswith(".jpg") or name.endswith(".jpeg"):
        ext = ".jpg"
    elif name.endswith(".webp"):
        ext = ".webp"
    elif name.endswith(".png"):
        ext = ".png"
    else:
        raise HTTPException(400, "Upload png, jpg, or webp")
    root = Path(DATA_DIR) / "presence" / "portraits"
    root.mkdir(parents=True, exist_ok=True)
    # Clear other extensions for this skin
    for old in root.glob(f"{sid}.*"):
        try:
            old.unlink()
        except OSError:
            pass
    dest = root / f"{sid}{ext}"
    data = await file.read()
    if len(data) > 12 * 1024 * 1024:
        raise HTTPException(400, "Portrait too large (max 12 MB)")
    dest.write_bytes(data)
    return {
        "ok": True,
        "skin_id": sid,
        "path": str(dest),
        "url": f"/api/presence/portrait/{sid}",
    }


@router.get("/api/presence/avatar/latest")
def presence_avatar_latest() -> dict[str, Any]:
    from friday.avatar.pipeline import render_for_active_skin
    from friday.presence.registry import active_skin_id, portrait_path_for

    sid = active_skin_id()
    portrait = portrait_path_for(sid)
    # Still-only status for HUD (lip-sync runs after TTS when enabled).
    result = render_for_active_skin(audio_path=None)
    return {
        "skin_id": sid,
        "portrait_url": f"/api/presence/portrait/{sid}" if portrait.is_file() else None,
        **result.as_dict(),
    }


@router.post("/api/presence/avatar/render")
def presence_avatar_render() -> dict[str, Any]:
    """Kick a still/lipsync render for the active skin (no audio → still)."""
    from friday.avatar.pipeline import render_for_active_skin

    return render_for_active_skin(audio_path=None).as_dict()
