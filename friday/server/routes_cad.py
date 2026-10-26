"""Systems / API for FreeCAD + Taiga-S1 CAD."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(tags=["cad"])


@router.get("/api/cad/status")
def cad_status() -> dict[str, Any]:
    from friday.cad.settings import resolve
    from friday.cad.status import probe_status

    st = probe_status()
    return {"ok": True, "status": st.as_dict(), "settings": resolve().as_dict()}


class CadPrefsBody(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)


@router.patch("/api/cad/prefs")
def cad_prefs_patch(body: CadPrefsBody) -> dict[str, Any]:
    from friday.cad.settings import CAD_PREF_KEYS, apply_patch, resolve
    from friday.cad.status import probe_status

    unknown = [k for k in body.values if k not in CAD_PREF_KEYS]
    if unknown:
        raise HTTPException(400, f"Unknown CAD prefs: {', '.join(unknown)}")
    apply_patch(body.values)
    return {"ok": True, "settings": resolve().as_dict(), "status": probe_status().as_dict()}


@router.post("/api/cad/detect")
def cad_detect() -> dict[str, Any]:
    from friday.cad.settings import detect_freecad_installs, seed_from_detect
    from friday.cad.status import probe_status

    found = [str(p) for p in detect_freecad_installs()]
    settings = seed_from_detect(enable=True) if found else None
    return {
        "ok": bool(found),
        "found": found,
        "settings": settings.as_dict() if settings else None,
        "status": probe_status().as_dict(),
    }


@router.post("/api/cad/setup")
def cad_setup() -> dict[str, Any]:
    from friday.cad.bootstrap import bootstrap
    from friday.cad.status import probe_status

    result = bootstrap(enable=True)
    return {"ok": result.ok, "setup": result.as_dict(), "status": probe_status().as_dict()}


@router.post("/api/cad/launch")
def cad_launch() -> dict[str, Any]:
    from friday.cad.launch import ensure_gui_server
    from friday.cad.status import probe_status

    result = ensure_gui_server()
    return {"ok": result.ok, "launch": result.as_dict(), "status": probe_status().as_dict()}
