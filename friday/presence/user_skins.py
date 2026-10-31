"""User-created presence callsigns — style/voice/portrait only; tools & safety unchanged."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from friday.presence.skins import PresenceSkin

_BUILTIN_IDS = frozenset(
    {"friday", "jarvis", "ultron", "vision", "karen", "edith"}
)
_ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")
_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

_VOICE_DEFAULTS = {
    "female_us": ("af_bella", "en-US-AvaNeural", "female_us"),
    "female_gb": ("bf_emma", "en-GB-SoniaNeural", "female_gb"),
    "male_us": ("am_adam", "en-US-DavisNeural", "male_us"),
    "male_gb": ("bm_george", "en-GB-RyanNeural", "male_gb"),
}

_ALLOWED_VOICES = frozenset(
    {
        "af_heart",
        "af_bella",
        "af_nicole",
        "af_sarah",
        "af_sky",
        "bf_emma",
        "bf_isabella",
        "am_adam",
        "am_michael",
        "am_puck",
        "bm_george",
        "bm_lewis",
        "bm_fable",
        "en-US-AvaNeural",
        "en-US-JennyNeural",
        "en-US-AriaNeural",
        "en-US-DavisNeural",
        "en-GB-SoniaNeural",
        "en-GB-RyanNeural",
        "en-GB-ThomasNeural",
    }
)


def _root() -> Path:
    from friday.config import DATA_DIR

    p = Path(DATA_DIR) / "presence" / "user_skins"
    p.mkdir(parents=True, exist_ok=True)
    return p


def slugify_name(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", (name or "").strip().lower()).strip("_")
    if not base:
        base = "persona"
    if not base[0].isalpha():
        base = "p_" + base
    return f"custom_{base[:24]}"


def is_builtin(skin_id: str) -> bool:
    return (skin_id or "").strip().lower() in _BUILTIN_IDS


def is_custom_id(skin_id: str) -> bool:
    sid = (skin_id or "").strip().lower()
    return sid.startswith("custom_") and _ID_RE.match(sid) is not None


def _path_for(skin_id: str) -> Path:
    return _root() / f"{skin_id.strip().lower()}.json"


def load_user_dict(skin_id: str) -> dict[str, Any] | None:
    path = _path_for(skin_id)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    return raw if isinstance(raw, dict) else None


def dict_to_skin(data: dict[str, Any]) -> PresenceSkin | None:
    sid = str(data.get("id") or "").strip().lower()
    if not is_custom_id(sid):
        return None
    name = str(data.get("display_name") or sid.replace("custom_", "").replace("_", " ")).strip()
    if not name:
        return None
    callsign = str(data.get("callsign") or name.upper()).strip()[:32] or name.upper()
    tts_voice = str(data.get("tts_voice") or "af_bella").strip()
    if tts_voice not in _ALLOWED_VOICES:
        tts_voice = "af_bella"
    voice_profile = str(data.get("voice_profile") or "female_us").strip().lower()
    if voice_profile not in _VOICE_DEFAULTS:
        voice_profile = "female_us"
    tts_edge = str(data.get("tts_edge") or "").strip()
    if not tts_edge:
        tts_edge = _VOICE_DEFAULTS[voice_profile][1]
    humor = str(data.get("humor_level") or "dry").strip().lower()
    if humor not in {"off", "dry", "full"}:
        humor = "dry"
    accent = str(data.get("accent") or "#3dd6c6").strip()
    if not _HEX_RE.match(accent):
        accent = "#3dd6c6"
    style = str(data.get("style_delta") or "").strip()[:1200]
    if not style:
        style = (
            f"Callsign {name}: speak in character with the owner's personality notes. "
            "Short spoken sentences. You are an inspired local callsign on this PC, not a film character."
        )
    identity = str(data.get("identity_line") or "").strip()[:400]
    if not identity:
        identity = (
            f"{name} — your local assistant callsign on this PC, {{owner}}. "
            "I run here, I speak here, and I act with the same tools and safety as always."
        )
    forms_raw = data.get("address_forms") or []
    if isinstance(forms_raw, str):
        forms = tuple(
            x.strip() for x in forms_raw.replace(";", ",").split(",") if x.strip()
        )[:4]
    else:
        forms = tuple(str(x).strip() for x in forms_raw if str(x).strip())[:4]
    hud = str(data.get("hud_title") or f"{callsign} · LOCAL PROTOCOL").strip()[:64]
    return PresenceSkin(
        id=sid,
        callsign=callsign,
        display_name=name,
        hud_title=hud,
        css_theme="skin-custom",
        tts_voice=tts_voice,
        tts_edge=tts_edge,
        tts_rate=str(data.get("tts_rate") or "+0%").strip() or "+0%",
        voice_profile=voice_profile,
        humor_level=humor if humor != "off" else "dry",
        accent=accent,
        style_delta=style,
        identity_line=identity,
        address_forms=forms,
        humor_bank=(),
    )


def list_user_skins() -> list[PresenceSkin]:
    out: list[PresenceSkin] = []
    for path in sorted(_root().glob("custom_*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(raw, dict):
            continue
        skin = dict_to_skin(raw)
        if skin:
            out.append(skin)
    return out


def get_user_skin(skin_id: str) -> PresenceSkin | None:
    sid = (skin_id or "").strip().lower()
    if not is_custom_id(sid):
        return None
    raw = load_user_dict(sid)
    return dict_to_skin(raw) if raw else None


def skin_exists(skin_id: str) -> bool:
    sid = (skin_id or "").strip().lower()
    if is_builtin(sid):
        return True
    return get_user_skin(sid) is not None


def _normalize_payload(body: dict[str, Any], *, skin_id: str | None = None) -> dict[str, Any]:
    name = str(body.get("display_name") or body.get("name") or "").strip()
    if not name or len(name) < 2:
        raise ValueError("Display name is required (at least 2 characters).")
    if len(name) > 40:
        raise ValueError("Display name too long (max 40).")
    sid = (skin_id or str(body.get("id") or "").strip().lower() or slugify_name(name))
    if not is_custom_id(sid):
        # Force custom_ prefix for free-form ids.
        sid = slugify_name(sid if sid.startswith("custom_") else name)
    if is_builtin(sid) or sid in _BUILTIN_IDS:
        raise ValueError("Cannot overwrite a built-in callsign.")
    if not _ID_RE.match(sid):
        raise ValueError("Invalid callsign id.")

    callsign = str(body.get("callsign") or name.upper()).strip()[:32]
    voice_profile = str(body.get("voice_profile") or "female_us").strip().lower()
    if voice_profile not in _VOICE_DEFAULTS:
        voice_profile = "female_us"
    tts_voice = str(body.get("tts_voice") or _VOICE_DEFAULTS[voice_profile][0]).strip()
    if tts_voice not in _ALLOWED_VOICES:
        tts_voice = _VOICE_DEFAULTS[voice_profile][0]
    tts_edge = str(body.get("tts_edge") or _VOICE_DEFAULTS[voice_profile][1]).strip()
    humor = str(body.get("humor_level") or "dry").strip().lower()
    if humor not in {"off", "dry", "full"}:
        humor = "dry"
    accent = str(body.get("accent") or "#3dd6c6").strip()
    if not _HEX_RE.match(accent):
        accent = "#3dd6c6"
    personality = str(
        body.get("personality") or body.get("style_delta") or ""
    ).strip()[:1200]
    if not personality:
        personality = (
            f"Callsign {name}: calm, clear, and helpful. Short spoken sentences. "
            "Stay in character. Inspired local callsign only — not a film character."
        )
    else:
        # Ensure callsign framing so the model doesn't invent film lore.
        if "callsign" not in personality.lower():
            personality = f"Callsign {name}: {personality}"
        if "film" not in personality.lower() and "inspired" not in personality.lower():
            personality = (
                personality.rstrip(".")
                + ". You are an inspired local callsign on this PC, not a film character."
            )
    identity = str(body.get("identity_line") or "").strip()[:400]
    if not identity:
        identity = (
            f"{name} — your local assistant on this PC, {{owner}}. "
            "I run here, I speak with you here, and I use the same tools and safety as always."
        )
    elif "{owner}" not in identity:
        identity = identity.rstrip(".") + ", {owner}."
    forms_raw = body.get("address_forms") or body.get("address_as") or ""
    if isinstance(forms_raw, str):
        forms = [x.strip() for x in forms_raw.replace(";", ",").split(",") if x.strip()][
            :4
        ]
    else:
        forms = [str(x).strip() for x in forms_raw if str(x).strip()][:4]
    lipsync = bool(body.get("lipsync", body.get("prefer_lipsync", False)))
    return {
        "id": sid,
        "display_name": name,
        "callsign": callsign,
        "hud_title": str(body.get("hud_title") or f"{callsign} · LOCAL PROTOCOL")[
            :64
        ],
        "css_theme": "skin-custom",
        "tts_voice": tts_voice,
        "tts_edge": tts_edge,
        "tts_rate": str(body.get("tts_rate") or "+0%")[:8] or "+0%",
        "voice_profile": voice_profile,
        "humor_level": "dry" if humor == "off" else humor,
        "accent": accent,
        "style_delta": personality,
        "identity_line": identity,
        "address_forms": forms,
        "lipsync": lipsync,
        "custom": True,
    }


def save_user_skin(body: dict[str, Any], *, skin_id: str | None = None) -> PresenceSkin:
    data = _normalize_payload(body, skin_id=skin_id)
    sid = data["id"]
    # Unique id on create when colliding
    if skin_id is None and _path_for(sid).is_file():
        n = 2
        while _path_for(f"{sid}_{n}").is_file() and n < 99:
            n += 1
        data["id"] = f"{sid}_{n}"
        sid = data["id"]
    path = _path_for(sid)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    skin = dict_to_skin(data)
    if not skin:
        raise ValueError("Failed to build callsign.")
    return skin


def delete_user_skin(skin_id: str) -> bool:
    sid = (skin_id or "").strip().lower()
    if not is_custom_id(sid) or is_builtin(sid):
        return False
    path = _path_for(sid)
    if not path.is_file():
        return False
    path.unlink(missing_ok=True)
    # Drop portrait + lipsync artifacts for this id
    try:
        from friday.config import DATA_DIR

        root = Path(DATA_DIR) / "presence"
        for p in (root / "portraits").glob(f"{sid}.*"):
            p.unlink(missing_ok=True)
        out = root / "avatar_out" / sid
        if out.is_dir():
            for child in out.iterdir():
                child.unlink(missing_ok=True)
            out.rmdir()
    except Exception:  # noqa: BLE001
        pass
    return True


def user_skin_meta(skin_id: str) -> dict[str, Any]:
    """Extra fields (lipsync prefer) not on PresenceSkin."""
    raw = load_user_dict(skin_id) or {}
    return {
        "custom": True,
        "lipsync": bool(raw.get("lipsync", False)),
    }


def voice_choices() -> list[dict[str, str]]:
    return [
        {"id": "af_bella", "label": "Bella (female US)", "profile": "female_us"},
        {"id": "af_heart", "label": "Heart (female US)", "profile": "female_us"},
        {"id": "af_nicole", "label": "Nicole (female US)", "profile": "female_us"},
        {"id": "af_sarah", "label": "Sarah (female US)", "profile": "female_us"},
        {"id": "bf_emma", "label": "Emma (female GB)", "profile": "female_gb"},
        {"id": "am_adam", "label": "Adam (male US)", "profile": "male_us"},
        {"id": "am_michael", "label": "Michael (male US)", "profile": "male_us"},
        {"id": "am_puck", "label": "Puck (male US)", "profile": "male_us"},
        {"id": "bm_george", "label": "George (male GB)", "profile": "male_gb"},
        {"id": "bm_lewis", "label": "Lewis (male GB)", "profile": "male_gb"},
    ]
