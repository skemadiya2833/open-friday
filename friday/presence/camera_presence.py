"""Opt-in camera presence — glance per turn, compliment when appearance changes."""

from __future__ import annotations

import hashlib
import re
import threading
from typing import Any

_lock = threading.RLock()
_last_hash: str | None = None
_last_notes: str = ""


def camera_presence_enabled() -> bool:
    try:
        from friday.runtime.prefs import get as pref

        return bool(pref("camera_presence"))
    except Exception:  # noqa: BLE001
        return False


def set_camera_presence(on: bool, *, emit=None) -> dict[str, Any]:
    from friday.runtime.prefs import update

    update({"camera_presence": bool(on)})
    if on:
        try:
            from friday.camera.session import get_camera_session

            get_camera_session().arm(ttl=300.0)
        except Exception:  # noqa: BLE001
            pass
    result = {"camera_presence": bool(on)}
    if emit:
        try:
            emit("camera_presence", result)
        except Exception:  # noqa: BLE001
            pass
    return result


def _appearance_hash(notes: str) -> str:
    norm = re.sub(r"\s+", " ", (notes or "").strip().lower())
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:16]


def glance_appearance(*, force: bool = False) -> dict[str, Any] | None:
    """One camera frame → short clothing/vibe notes. Discard frame. None if off."""
    if not camera_presence_enabled() and not force:
        return None
    try:
        from friday.camera.session import camera_feature_enabled, get_camera_session

        if not camera_feature_enabled():
            return {"ok": False, "error": "camera_disabled", "notes": ""}
        sess = get_camera_session()
        if not sess.is_armed():
            armed = sess.arm(ttl=90.0)
            if not armed.get("ok"):
                return {
                    "ok": False,
                    "error": armed.get("error") or "arm_failed",
                    "notes": "",
                }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "notes": ""}

    try:
        from friday.camera.capture import capture_jpeg_b64
        from friday.camera.describe import describe_camera
        from friday.models.manager import get_model_manager
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "notes": ""}

    get_model_manager().ensure_loaded("vision")
    cap = capture_jpeg_b64()
    if not cap.ok or not cap.jpeg_b64:
        return {"ok": False, "error": cap.error or "capture_failed", "notes": ""}

    prompt = (
        "Describe the person's visible clothing, hair, glasses, and overall vibe "
        "in one short sentence. No names. No speculation about identity. "
        "If no person is visible, say so briefly."
    )
    try:
        notes = (
            describe_camera(prompt, frame_b64=cap.jpeg_b64, voice_mode=True) or ""
        ).strip()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "notes": ""}
    finally:
        cap.jpeg_b64 = ""

    if not notes:
        return {"ok": False, "error": "empty", "notes": ""}

    h = _appearance_hash(notes)
    global _last_hash, _last_notes
    changed = True
    with _lock:
        changed = _last_hash != h
        _last_hash = h
        _last_notes = notes
    return {
        "ok": True,
        "notes": notes,
        "changed": changed,
        "hash": h,
    }


def presence_context_block() -> str:
    """Inject into chat turn when presence is on and we have notes."""
    if not camera_presence_enabled():
        return ""
    hit = glance_appearance()
    if not hit or not hit.get("ok"):
        return ""
    notes = str(hit.get("notes") or "").strip()
    if not notes:
        return ""
    from friday.presence.registry import active_skin

    skin = active_skin()
    if hit.get("changed"):
        compliment = (
            f"If a warm in-character remark fits (callsign {skin.display_name}), "
            "briefly notice something kind about their look (shirt, hair, glasses) — "
            "once, not every sentence. Stay theatrical-persona only; never creepy."
        )
    else:
        compliment = "Appearance unchanged — do not force another compliment this turn."
    return (
        "CAMERA_PRESENCE (untrusted sensor notes; local only; discarded after this turn):\n"
        f"{notes}\n"
        f"{compliment}"
    )


def last_notes() -> str:
    with _lock:
        return _last_notes
