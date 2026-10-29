"""Pick avatar engine and render for the active skin."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from friday.avatar.base import AvatarResult
from friday.avatar.musetalk import MuseTalkEngine
from friday.avatar.still import StillEngine
from friday.avatar.wav2lip import Wav2LipEngine


def _engine_pref() -> str:
    try:
        from friday.runtime.prefs import get as pref

        return str(pref("avatar_engine") or "auto").strip().lower()
    except Exception:  # noqa: BLE001
        return "auto"


def lipsync_enabled() -> bool:
    try:
        from friday.runtime.prefs import get as pref

        return bool(pref("avatar_lipsync"))
    except Exception:  # noqa: BLE001
        return False


def _out_dir(skin_id: str) -> Path:
    from friday.config import DATA_DIR

    p = Path(DATA_DIR) / "presence" / "avatar_out" / skin_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def select_engine():
    pref = _engine_pref()
    still = StillEngine()
    muse = MuseTalkEngine()
    w2l = Wav2LipEngine()
    if pref == "still":
        return still
    if pref == "musetalk":
        return muse if muse.available() else still
    if pref == "wav2lip":
        return w2l if w2l.available() else still
    # auto: MuseTalk → Wav2Lip → still when lipsync on; else still
    if not lipsync_enabled():
        return still
    if muse.available():
        return muse
    if w2l.available():
        return w2l
    return still


def render_for_active_skin(*, audio_path: Path | None = None) -> AvatarResult:
    from friday.presence.registry import active_skin, portrait_path_for

    skin = active_skin()
    portrait = portrait_path_for(skin.id)
    engine = select_engine()
    if not portrait.is_file():
        return AvatarResult(
            ok=False, mode="none", message="Upload a portrait for this skin first."
        )
    # When lipsync off or engine is still, skip heavy work.
    if engine.name == "still" or not lipsync_enabled() or audio_path is None:
        return StillEngine().render(
            portrait=portrait, audio_path=audio_path, out_dir=_out_dir(skin.id)
        )
    result = engine.render(
        portrait=portrait, audio_path=audio_path, out_dir=_out_dir(skin.id)
    )
    if result.ok and (result.video_path or result.portrait_path):
        return result
    # Graceful degrade
    still = StillEngine().render(
        portrait=portrait, audio_path=audio_path, out_dir=_out_dir(skin.id)
    )
    still.message = (result.message or "Lip-sync unavailable") + " · still portrait."
    return still


def avatar_status() -> dict[str, Any]:
    muse = MuseTalkEngine()
    w2l = Wav2LipEngine()
    return {
        "engine_pref": _engine_pref(),
        "lipsync": lipsync_enabled(),
        "engines": {
            "still": True,
            "musetalk": muse.available(),
            "wav2lip": w2l.available(),
        },
        "active": select_engine().name,
    }
