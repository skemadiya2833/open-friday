"""Avatar engines — talking-video first; Wav2Lip retired from the default path."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from friday.avatar.base import AvatarResult
from friday.avatar.still import StillEngine


def _engine_pref() -> str:
    try:
        from friday.runtime.prefs import get as pref

        return str(pref("avatar_engine") or "auto").strip().lower()
    except Exception:  # noqa: BLE001
        return "auto"


def lipsync_enabled() -> bool:
    """True when the active callsign has a talking video (or legacy pref on)."""
    try:
        from friday.presence.registry import active_skin_id
        from friday.presence.talking import has_talking_video
        from friday.runtime.prefs import get as pref

        if has_talking_video(active_skin_id()):
            return True
        return bool(pref("avatar_lipsync"))
    except Exception:  # noqa: BLE001
        return False


def _out_dir(skin_id: str) -> Path:
    from friday.config import DATA_DIR

    p = Path(DATA_DIR) / "presence" / "avatar_out" / skin_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def select_engine():
    """Talking video is client-side; server engine is still-only unless forced legacy."""
    pref = _engine_pref()
    still = StillEngine()
    if pref in {"still", "talking", "auto"}:
        return still
    # Legacy opt-in only — not used by default.
    if pref == "wav2lip":
        try:
            from friday.avatar.wav2lip import Wav2LipEngine

            w2l = Wav2LipEngine()
            return w2l if w2l.available() else still
        except Exception:  # noqa: BLE001
            return still
    if pref == "musetalk":
        try:
            from friday.avatar.musetalk import MuseTalkEngine

            muse = MuseTalkEngine()
            return muse if muse.available() else still
        except Exception:  # noqa: BLE001
            return still
    return still


def render_for_active_skin(*, audio_path: Path | None = None) -> AvatarResult:
    """Still portrait path. Talking clips are played in the HUD against TTS."""
    from friday.presence.registry import active_skin, portrait_path_for
    from friday.presence.talking import has_talking_video, talking_video_path

    skin = active_skin()
    portrait = portrait_path_for(skin.id)
    if has_talking_video(skin.id):
        return AvatarResult(
            ok=True,
            mode="talking",
            portrait_path=str(portrait.resolve()) if portrait.is_file() else None,
            video_path=str(talking_video_path(skin.id).resolve()),
            message="Talking video ready — HUD syncs it to speech.",
        )
    if not portrait.is_file():
        return AvatarResult(
            ok=False, mode="none", message="Upload a portrait or talking video first."
        )
    engine = select_engine()
    if engine.name == "still" or audio_path is None:
        return StillEngine().render(
            portrait=portrait, audio_path=audio_path, out_dir=_out_dir(skin.id)
        )
    # Legacy Wav2Lip/MuseTalk only when engine pref forces it.
    result = engine.render(
        portrait=portrait, audio_path=audio_path, out_dir=_out_dir(skin.id)
    )
    if result.ok and (result.video_path or result.portrait_path):
        return result
    still = StillEngine().render(
        portrait=portrait, audio_path=audio_path, out_dir=_out_dir(skin.id)
    )
    still.message = (result.message or "Avatar engine unavailable") + " · still portrait."
    return still


def avatar_status() -> dict[str, Any]:
    from friday.presence.registry import active_skin_id
    from friday.presence.talking import has_talking_video

    try:
        from friday.avatar.wav2lip import Wav2LipEngine

        w2l_ok = Wav2LipEngine().available()
    except Exception:  # noqa: BLE001
        w2l_ok = False
    try:
        from friday.avatar.musetalk import MuseTalkEngine

        muse_ok = MuseTalkEngine().available()
    except Exception:  # noqa: BLE001
        muse_ok = False
    sid = active_skin_id()
    talking = has_talking_video(sid)
    return {
        "engine_pref": _engine_pref(),
        "lipsync": lipsync_enabled(),
        "talking_video": talking,
        "engines": {
            "still": True,
            "talking": talking,
            "musetalk": muse_ok,
            "wav2lip": w2l_ok,
        },
        "active": "talking" if talking else select_engine().name,
        "note": "Upload a talking-head clip per callsign — HUD loops it with TTS. Wav2Lip is legacy-only.",
    }
