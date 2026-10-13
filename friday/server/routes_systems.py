"""Systems UI — runtime prefs (env knobs you can flip without editing .env)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(tags=["systems"])


@router.get("/api/systems/prefs")
def systems_prefs_get() -> dict[str, Any]:
    from friday.runtime.prefs import snapshot

    return snapshot()


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
