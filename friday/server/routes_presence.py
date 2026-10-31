"""Presence skins, portraits, avatar status, custom callsign CRUD."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

router = APIRouter(tags=["presence"])


def _require_skin(skin_id: str) -> str:
    from friday.presence.user_skins import skin_exists

    sid = skin_id.strip().lower()
    if not skin_exists(sid):
        raise HTTPException(404, f"Unknown skin: {sid}")
    return sid


@router.get("/api/presence")
def presence_get() -> dict[str, Any]:
    from friday.avatar.pipeline import avatar_status
    from friday.presence.registry import presence_snapshot
    from friday.presence.user_skins import voice_choices

    snap = presence_snapshot()
    snap["avatar"] = avatar_status()
    snap["voice_choices"] = voice_choices()
    return snap


class SkinBody(BaseModel):
    skin_id: str = Field(..., min_length=2, max_length=40)


@router.post("/api/presence/skin")
def presence_set_skin(body: SkinBody) -> dict[str, Any]:
    from friday.presence.registry import apply_skin

    sid = _require_skin(body.skin_id)
    try:
        return apply_skin(sid)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


class CustomSkinBody(BaseModel):
    display_name: str = Field(..., min_length=2, max_length=40)
    callsign: str | None = Field(None, max_length=32)
    personality: str | None = Field(None, max_length=1200)
    style_delta: str | None = Field(None, max_length=1200)
    identity_line: str | None = Field(None, max_length=400)
    address_forms: str | list[str] | None = None
    address_as: str | None = None
    tts_voice: str | None = Field(None, max_length=40)
    voice_profile: str | None = Field(None, max_length=16)
    humor_level: str | None = Field(None, max_length=8)
    accent: str | None = Field(None, max_length=7)
    lipsync: bool | None = None
    prefer_lipsync: bool | None = None
    activate: bool = True


@router.post("/api/presence/skins")
def presence_create_skin(body: CustomSkinBody) -> dict[str, Any]:
    """Create a custom callsign (inherits tools/safety; style + voice only)."""
    from friday.presence.registry import apply_skin, presence_snapshot
    from friday.presence.user_skins import save_user_skin

    payload = body.model_dump(exclude_none=True)
    try:
        skin = save_user_skin(payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    snap = (
        apply_skin(skin.id)
        if body.activate
        else presence_snapshot()
    )
    return {"ok": True, "skin": skin.as_dict(), **snap}


@router.patch("/api/presence/skins/{skin_id}")
def presence_update_skin(skin_id: str, body: CustomSkinBody) -> dict[str, Any]:
    from friday.presence.registry import apply_skin, presence_snapshot
    from friday.presence.user_skins import is_custom_id, load_user_dict, save_user_skin

    sid = skin_id.strip().lower()
    if not is_custom_id(sid):
        raise HTTPException(400, "Built-in callsigns cannot be edited here.")
    existing = load_user_dict(sid)
    if not existing:
        raise HTTPException(404, "Unknown custom callsign")
    payload = {**existing, **body.model_dump(exclude_none=True)}
    payload["id"] = sid
    try:
        skin = save_user_skin(payload, skin_id=sid)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    from friday.presence.registry import active_skin_id

    snap = apply_skin(sid) if active_skin_id() == sid else presence_snapshot()
    return {"ok": True, "skin": skin.as_dict(), **snap}


@router.delete("/api/presence/skins/{skin_id}")
def presence_delete_skin(skin_id: str) -> dict[str, Any]:
    from friday.presence.registry import active_skin_id, apply_skin, presence_snapshot
    from friday.presence.user_skins import delete_user_skin, is_custom_id

    sid = skin_id.strip().lower()
    if not is_custom_id(sid):
        raise HTTPException(400, "Built-in callsigns cannot be deleted.")
    was_active = active_skin_id() == sid
    if not delete_user_skin(sid):
        raise HTTPException(404, "Unknown custom callsign")
    snap = apply_skin("friday") if was_active else presence_snapshot()
    return {"ok": True, "deleted": sid, **snap}


@router.get("/api/presence/portrait/{skin_id}")
def presence_portrait(skin_id: str):
    from friday.presence.registry import portrait_path_for

    sid = _require_skin(skin_id)
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
    from friday.presence.registry import _schedule_ws_presence, presence_snapshot

    sid = _require_skin(skin_id)
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
    snap = presence_snapshot()
    _schedule_ws_presence(snap)
    return {
        "ok": True,
        "skin_id": sid,
        "path": str(dest),
        "url": f"/api/presence/portrait/{sid}",
        **snap,
    }


@router.delete("/api/presence/portrait/{skin_id}")
def presence_delete_portrait(skin_id: str) -> dict[str, Any]:
    """Remove the still portrait for a callsign."""
    from friday.config import DATA_DIR
    from friday.presence.registry import _schedule_ws_presence, presence_snapshot

    sid = _require_skin(skin_id)
    root = Path(DATA_DIR) / "presence" / "portraits"
    removed = False
    for old in root.glob(f"{sid}.*"):
        try:
            old.unlink()
            removed = True
        except OSError:
            pass
    snap = presence_snapshot()
    _schedule_ws_presence(snap)
    return {"ok": True, "deleted": sid if removed else None, **snap}


@router.get("/api/presence/talking/{skin_id}")
def presence_talking_get(skin_id: str):
    """Serve the uploaded talking-head clip for a callsign."""
    from friday.presence.talking import talking_video_path

    sid = _require_skin(skin_id)
    path = talking_video_path(sid)
    if not path.is_file() or path.stat().st_size < 1000:
        raise HTTPException(404, "No talking video uploaded")
    return FileResponse(
        path,
        media_type="video/mp4",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/api/presence/talking/{skin_id}/mouth")
def presence_talking_mouth(skin_id: str):
    """Mouth-segment atlas for HUD phonetic-ish seeking into the talking clip."""
    from friday.presence.mouth_atlas import load_mouth_atlas, write_mouth_atlas
    from friday.presence.talking import talking_video_path

    sid = _require_skin(skin_id)
    path = talking_video_path(sid)
    if not path.is_file() or path.stat().st_size < 1000:
        raise HTTPException(404, "No talking video uploaded")
    atlas = load_mouth_atlas(path)
    if atlas is None:
        try:
            write_mouth_atlas(path)
            atlas = load_mouth_atlas(path)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(500, f"Mouth atlas failed: {exc}") from exc
    if not atlas:
        raise HTTPException(404, "Mouth atlas unavailable")
    return atlas


@router.post("/api/presence/talking/{skin_id}")
async def presence_talking_upload(
    skin_id: str, file: UploadFile = File(...)
) -> dict[str, Any]:
    """Upload a talking-head mp4; HUD loops it (muted) while TTS speaks."""
    import tempfile

    from friday.presence.registry import _schedule_ws_presence, presence_snapshot
    from friday.presence.talking import (
        extract_portrait_from_video,
        install_talking_video,
        talking_video_url,
    )
    from friday.presence.registry import portrait_path_for

    sid = _require_skin(skin_id)
    name = (file.filename or "talking.mp4").lower()
    if not any(name.endswith(ext) for ext in (".mp4", ".webm", ".mov", ".mkv")):
        raise HTTPException(400, "Upload mp4 / webm / mov")
    data = await file.read()
    if len(data) > 80 * 1024 * 1024:
        raise HTTPException(400, "Talking video too large (max 80 MB)")
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        tmp.write(data)
        tmp_path = Path(tmp.name)
    try:
        dest = install_talking_video(sid, tmp_path)
        # Seed portrait from a frame if none exists yet.
        portrait = portrait_path_for(sid)
        if not portrait.is_file():
            try:
                extract_portrait_from_video(dest, portrait.with_suffix(".png"))
            except Exception:  # noqa: BLE001
                pass
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
    snap = presence_snapshot()
    _schedule_ws_presence(snap)
    return {
        "ok": True,
        "skin_id": sid,
        "url": talking_video_url(sid),
        **snap,
    }


@router.delete("/api/presence/talking/{skin_id}")
def presence_talking_delete(skin_id: str) -> dict[str, Any]:
    from friday.presence.mouth_atlas import mouth_atlas_path
    from friday.presence.registry import _schedule_ws_presence, presence_snapshot
    from friday.presence.talking import talking_video_path

    sid = _require_skin(skin_id)
    path = talking_video_path(sid)
    if path.is_file():
        path.unlink(missing_ok=True)
    atlas = mouth_atlas_path(path)
    if atlas.is_file():
        atlas.unlink(missing_ok=True)
    snap = presence_snapshot()
    _schedule_ws_presence(snap)
    return {"ok": True, "deleted": sid, **snap}


@router.get("/api/presence/avatar/latest")
def presence_avatar_latest() -> dict[str, Any]:
    """HUD status: portrait + talking video when uploaded."""
    from friday.avatar.pipeline import lipsync_enabled
    from friday.presence.registry import active_skin_id, portrait_path_for
    from friday.presence.talking import has_talking_video, talking_video_url

    sid = active_skin_id()
    portrait = portrait_path_for(sid)
    talk = talking_video_url(sid)
    return {
        "ok": True,
        "skin_id": sid,
        "lipsync": lipsync_enabled(),
        "mode": "talking" if has_talking_video(sid) else "still",
        "portrait_url": f"/api/presence/portrait/{sid}" if portrait.is_file() else None,
        "video_url": talk,
        "talking_video_url": talk,
        "message": (
            "Talking video ready — plays with speech."
            if talk
            else "Still portrait (upload a talking video on Systems → Presence)."
        ),
    }


@router.get("/api/presence/avatar/video/{skin_id}")
def presence_avatar_video(skin_id: str):
    """Back-compat alias → talking video."""
    return presence_talking_get(skin_id)


@router.post("/api/presence/avatar/render")
def presence_avatar_render() -> dict[str, Any]:
    """Status for active skin (talking video or still)."""
    from friday.avatar.pipeline import render_for_active_skin

    return render_for_active_skin(audio_path=None).as_dict()
