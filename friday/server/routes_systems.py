"""Systems UI — runtime prefs (env knobs you can flip without editing .env)."""

from __future__ import annotations

import threading
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(tags=["systems"])


@router.get("/api/systems/prefs")
def systems_prefs_get() -> dict[str, Any]:
    from friday.runtime.prefs import snapshot

    return snapshot()


@router.get("/api/systems/models")
def systems_models_list() -> dict[str, Any]:
    """Installed Ollama tags + currently resolved chat/vision (for Systems picker)."""
    from friday.config import OLLAMA_HOST, resolve_chat_model, resolve_vision_model

    tags: list[dict[str, Any]] = []
    try:
        import httpx

        r = httpx.get(f"{OLLAMA_HOST}/api/tags", timeout=5.0)
        r.raise_for_status()
        for m in (r.json() or {}).get("models") or []:
            name = str(m.get("name") or "").strip()
            if not name:
                continue
            size = m.get("size")
            tags.append(
                {
                    "name": name,
                    "size_gb": round(float(size) / (1024**3), 2) if size else None,
                }
            )
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error": str(exc),
            "models": [],
            "chat_model": resolve_chat_model(),
            "vision_model": resolve_vision_model(),
        }
    tags.sort(key=lambda x: x["name"].lower())
    return {
        "ok": True,
        "models": tags,
        "chat_model": resolve_chat_model(),
        "vision_model": resolve_vision_model(),
    }


class PrefsPatch(BaseModel):
    """Partial update. Omit keys to leave unchanged; set null to clear UI override."""

    values: dict[str, Any] = Field(default_factory=dict)


@router.patch("/api/systems/prefs")
def systems_prefs_patch(body: PrefsPatch) -> dict[str, Any]:
    from friday.runtime.prefs import SCHEMA, snapshot, update

    unknown = [k for k in body.values if k not in SCHEMA]
    if unknown:
        raise HTTPException(400, f"Unknown prefs: {', '.join(unknown)}")
    update(body.values)
    # Side effects that need sync beyond the prefs file
    _apply_side_effects(body.values)
    return snapshot()


@router.post("/api/systems/prefs/optima")
def systems_prefs_optima() -> dict[str, Any]:
    from friday.runtime.prefs import reset_to_optima, snapshot

    reset_to_optima()
    _apply_side_effects({"agent_backend": True, "humor": True})
    return snapshot()


@router.post("/api/systems/prefs/clear")
def systems_prefs_clear() -> dict[str, Any]:
    from friday.runtime.prefs import clear_all, snapshot

    clear_all()
    _apply_side_effects({"agent_backend": True, "humor": True})
    return snapshot()


@router.get("/api/systems/profile")
def systems_profile_get() -> dict[str, Any]:
    from friday.runtime.owner_profile import load

    return load()


class ProfilePatch(BaseModel):
    about: str | None = None
    upgrades: list[Any] | None = None


@router.patch("/api/systems/profile")
def systems_profile_patch(body: ProfilePatch) -> dict[str, Any]:
    from friday.runtime.owner_profile import update

    return update(about=body.about, upgrades=body.upgrades)


class UpgradeAdd(BaseModel):
    text: str = Field(..., min_length=1, max_length=280)
    source: str = "manual"


@router.post("/api/systems/profile/upgrades")
def systems_profile_add_upgrade(body: UpgradeAdd) -> dict[str, Any]:
    from friday.runtime.owner_profile import add_upgrade

    try:
        return add_upgrade(body.text, source=body.source)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.delete("/api/systems/profile/upgrades/{index}")
def systems_profile_del_upgrade(index: int) -> dict[str, Any]:
    from friday.runtime.owner_profile import load, save

    data = load()
    ups = list(data.get("upgrades") or [])
    if index < 0 or index >= len(ups):
        raise HTTPException(404, "Not found")
    ups.pop(index)
    data["upgrades"] = ups
    return save(data)


def _apply_side_effects(patch: dict[str, Any]) -> None:
    """Invalidate caches / request overrides after a prefs write."""
    if "agent_backend" in patch:
        try:
            from friday.agent.backend import clear_backend_cache

            clear_backend_cache()
        except Exception:  # noqa: BLE001
            pass
    if "humor" in patch:
        try:
            from friday.humor import set_humor_override

            set_humor_override(None)
        except Exception:  # noqa: BLE001
            pass
    if "presence_skin" in patch:
        try:
            from friday.presence.skins import get_skin
            from friday.runtime.prefs import get as pref_get
            from friday.runtime.prefs import update as prefs_update

            # Sync TTS + humor to the skin without re-entering apply_skin (already patched).
            skin = get_skin(str(pref_get("presence_skin") or "friday"))
            prefs_update({"tts_voice": skin.tts_voice, "humor": skin.humor_level})
            from friday.presence.registry import presence_snapshot

            snap = presence_snapshot()
            from friday.presence.registry import _schedule_ws_presence

            _schedule_ws_presence(snap)
        except Exception:  # noqa: BLE001
            pass
    if "chat_model" in patch or "vision_model" in patch:
        try:
            from friday import config as C

            C._ollama_tags_cache = None
        except Exception:  # noqa: BLE001
            pass
        try:
            from friday.models.manager import get_model_manager

            # Same tag for chat+vision → keep resident; only unload if the hot tag is obsolete.
            get_model_manager().on_prefs_model_change()
        except Exception:  # noqa: BLE001
            pass
    if any(k in patch for k in ("telegram_enabled", "telegram_bot_token", "telegram_allowed_chat_ids")):
        try:
            from friday.channels.telegram import sync_from_prefs

            sync_from_prefs()
        except Exception:  # noqa: BLE001
            pass
    if "cua_enabled" in patch:
        try:
            from friday.mcp_client import get_mcp_manager

            mgr = get_mcp_manager()
            from friday.runtime.prefs import get as pref_get

            if pref_get("cua_enabled"):
                mgr.start("cua")
            else:
                mgr.stop("cua")
        except Exception:  # noqa: BLE001
            pass
    if "artemis_enabled" in patch:
        try:
            from friday.mcp_client import get_mcp_manager
            from friday.runtime.bootstrap_integrations import ensure_artemis
            from friday.runtime.prefs import get as pref_get

            mgr = get_mcp_manager()
            if pref_get("artemis_enabled"):
                # Clone/venv off the request thread; MCP start retries once ready.
                threading.Thread(
                    target=lambda: (ensure_artemis(force=True), mgr.start("artemis")),
                    name="friday-artemis-boot",
                    daemon=True,
                ).start()
            else:
                mgr.stop("artemis")
        except Exception:  # noqa: BLE001
            pass
    if "skill_proposals" in patch:
        try:
            import os

            from friday.runtime.prefs import get as pref_get

            os.environ["SKILL_PROPOSALS"] = "true" if pref_get("skill_proposals") else "false"
        except Exception:  # noqa: BLE001
            pass
