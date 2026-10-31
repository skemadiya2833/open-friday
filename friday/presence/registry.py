"""Active presence skin — prefs + notify HUD."""

from __future__ import annotations

from typing import Any

from friday.presence.skins import (
    CAPABILITY_CLAMP,
    DEFAULT_SKIN_ID,
    PresenceSkin,
    get_skin,
    list_skins,
)


def active_skin_id() -> str:
    try:
        from friday.runtime.prefs import get as pref

        return (
            str(pref("presence_skin") or DEFAULT_SKIN_ID).strip().lower()
            or DEFAULT_SKIN_ID
        )
    except Exception:  # noqa: BLE001
        return DEFAULT_SKIN_ID


def active_skin() -> PresenceSkin:
    return get_skin(active_skin_id())


def spoken_address() -> str:
    """How the active callsign addresses the owner (sir / boss / boy…).

    Multi-form skins (Ultron boy|old man) rotate on a ~45s bucket so one reply
    never flips honorific mid-sentence when owner_name() is called twice.
    """
    import time

    skin = active_skin()
    forms = tuple(getattr(skin, "address_forms", ()) or ())
    if forms:
        if len(forms) == 1:
            return forms[0]
        return forms[int(time.time() // 45) % len(forms)]
    try:
        from friday.runtime.prefs import get as pref

        name = str(pref("owner_name") or "").strip()
        if name:
            return name
    except Exception:  # noqa: BLE001
        pass
    import os

    return (os.environ.get("FRIDAY_OWNER_NAME") or "boss").strip() or "boss"


def prompt_presence_block(*, kind: str = "chat") -> str:
    """Short style delta + clamp for chat/voice/agent — never dump lore novels."""
    if kind in {"observe", "observe_voice"}:
        return ""
    skin = active_skin()
    addr = spoken_address()
    forms = ", ".join(skin.address_forms) if skin.address_forms else addr
    # Keep this tight: long clamps get recited. Style is performance; safety is absolute.
    return (
        f"Callsign {skin.display_name}. Address them as {forms}. "
        f"{skin.style_delta} "
        f"{CAPABILITY_CLAMP}"
    )


def presence_snapshot() -> dict[str, Any]:
    skin = active_skin()
    portrait = portrait_path_for(skin.id)
    portraits: dict[str, str | None] = {}
    for s in list_skins():
        p = portrait_path_for(s.id)
        portraits[s.id] = (
            f"/api/presence/portrait/{s.id}" if p is not None and p.is_file() else None
        )
    from friday.presence.talking import has_talking_video, mouth_atlas_url, talking_video_url

    skins_out: list[dict[str, Any]] = []
    try:
        from friday.presence.user_skins import is_custom_id, user_skin_meta

        for s in list_skins():
            d = s.as_dict()
            if is_custom_id(s.id):
                d.update(user_skin_meta(s.id))
            else:
                d["custom"] = False
            d["talking_video"] = has_talking_video(s.id)
            skins_out.append(d)
        skin_d = skin.as_dict()
        if is_custom_id(skin.id):
            skin_d.update(user_skin_meta(skin.id))
        else:
            skin_d["custom"] = False
        skin_d["talking_video"] = has_talking_video(skin.id)
    except Exception:  # noqa: BLE001
        skins_out = [s.as_dict() for s in list_skins()]
        skin_d = skin.as_dict()
        skin_d["custom"] = False
        skin_d["talking_video"] = has_talking_video(skin.id)

    talk_url = talking_video_url(skin.id)
    return {
        "skin": skin_d,
        "skins": skins_out,
        "camera_presence": bool(_pref_bool("camera_presence", False)),
        "avatar_engine": str(_pref_str("avatar_engine", "auto") or "auto"),
        "avatar_lipsync": bool(_pref_bool("avatar_lipsync", False)),
        "portrait_url": f"/api/presence/portrait/{skin.id}"
        if portrait and portrait.is_file()
        else None,
        # Prefer uploaded talking clip (TTS-synced in the HUD) over generated lipsync.
        "video_url": talk_url,
        "talking_video_url": talk_url,
        "mouth_atlas_url": mouth_atlas_url(skin.id) if talk_url else None,
        "portraits": portraits,
        "clamp": CAPABILITY_CLAMP,
    }


def portrait_path_for(skin_id: str):
    from pathlib import Path

    from friday.config import DATA_DIR

    root = Path(DATA_DIR) / "presence" / "portraits"
    for ext in (".png", ".jpg", ".jpeg", ".webp"):
        p = root / f"{skin_id}{ext}"
        if p.is_file():
            return p
    return root / f"{skin_id}.png"


def apply_skin(skin_id: str, *, emit=None) -> dict[str, Any]:
    """Switch callsign pack: prefs, TTS voice, humor level. Capabilities unchanged."""
    from friday.presence.user_skins import get_user_skin, skin_exists, user_skin_meta

    sid = (skin_id or "").strip().lower()
    if not skin_exists(sid):
        raise ValueError(f"Unknown skin: {sid}")
    skin = get_skin(sid)
    from friday.runtime.prefs import update

    # Prefer Kokoro character voice; flip engine so Ultron never lands on female remaps.
    engine = (
        "kokoro" if skin.tts_voice.startswith(("af_", "bf_", "am_", "bm_")) else "edge"
    )
    patch: dict[str, Any] = {
        "presence_skin": skin.id,
        "tts_voice": skin.tts_voice,
        "tts_engine": engine,
        "humor": skin.humor_level,
    }
    # Talking video callsigns keep the speak-with-clip toggle on.
    try:
        from friday.presence.talking import has_talking_video

        if has_talking_video(skin.id):
            patch["avatar_lipsync"] = True
        elif get_user_skin(skin.id) is not None:
            patch["avatar_lipsync"] = bool(user_skin_meta(skin.id).get("lipsync"))
    except Exception:  # noqa: BLE001
        pass
    update(patch)
    try:
        from friday.humor import set_humor_override

        set_humor_override(None)
    except Exception:  # noqa: BLE001
        pass

    snap = presence_snapshot()
    if emit:
        try:
            emit("presence", snap)
        except Exception:  # noqa: BLE001
            pass
    _schedule_ws_presence(snap)
    warm_tts_voice(skin.tts_voice)
    return snap


def warm_tts_voice(voice: str | None = None) -> None:
    """Prime Kokoro worker in the background so the first spoken reply starts faster."""
    import threading

    v = (voice or "").strip() or active_skin().tts_voice

    def _run() -> None:
        try:
            from friday.voice.tts import synthesize_bytes

            synthesize_bytes("Ready.", voice=v)
        except Exception:  # noqa: BLE001
            pass

    threading.Thread(target=_run, daemon=True, name="FridayTtsWarm").start()


def _pref_bool(key: str, default: bool) -> bool:
    try:
        from friday.runtime.prefs import get as pref

        return bool(pref(key))
    except Exception:  # noqa: BLE001
        return default


def _pref_str(key: str, default: str) -> str:
    try:
        from friday.runtime.prefs import get as pref

        return str(pref(key) or default)
    except Exception:  # noqa: BLE001
        return default


def _schedule_ws_presence(snap: dict[str, Any]) -> None:
    """Best-effort HUD push when an event loop is running."""
    try:
        import asyncio

        from friday.server.app import broadcast

        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.run_coroutine_threadsafe(
                broadcast({"type": "presence", **snap}),
                loop,
            )
    except Exception:  # noqa: BLE001
        pass
