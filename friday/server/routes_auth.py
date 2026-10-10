"""Passkey pairing, registration, login, device admin, step-up."""

from __future__ import annotations

import secrets
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from friday.auth.config import get_auth_config
from friday.auth.roles import Role, parse_role, role_at_least
from friday.auth.store import get_store
from friday.auth import webauthn_flow as WA

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _audit(tool: str, **kw: Any) -> None:
    try:
        from friday.safety.audit import get_audit_log

        get_audit_log().record(tool=tool, args=kw.get("args") or {}, outcome=kw.get("outcome", "ok"),
                               approver=kw.get("approver", "auth"), risk="safe", caller="auth",
                               detail=str(kw.get("detail") or "")[:500])
    except Exception:  # noqa: BLE001
        pass


def _soft(request: Request) -> dict[str, Any]:
    return {
        "ua": (request.headers.get("user-agent") or "")[:200],
        "ip": request.client.host if request.client else "",
        "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def _session_from_request(request: Request) -> dict[str, Any] | None:
    cfg = get_auth_config()
    sid = request.cookies.get(cfg.cookie_name)
    if not sid:
        return None
    return get_store().get_session(sid)


def require_session(request: Request, *, min_role: Role = Role.CHAT) -> dict[str, Any]:
    cfg = get_auth_config()
    if cfg.mode == "off":
        return {"id": "dev", "device_id": "dev", "role": Role.ADMIN.value}
    sess = _session_from_request(request)
    if not sess:
        raise HTTPException(401, "authentication required")
    if not role_at_least(sess.get("role", "chat"), min_role):
        raise HTTPException(403, "insufficient role")
    return sess


def require_stepup(request: Request) -> dict[str, Any]:
    sess = require_session(request, min_role=Role.ADMIN)
    if get_auth_config().mode == "off":
        return sess
    if not get_store().stepup_ok(sess["id"]):
        raise HTTPException(403, "step-up passkey verification required")
    return sess


class PairRequest(BaseModel):
    device_name: str = Field(min_length=1, max_length=64)


class PairApprove(BaseModel):
    pending_id: str
    code: str = Field(min_length=6, max_length=6)


class RegVerify(BaseModel):
    enrollment_token: str
    challenge: str
    credential: dict[str, Any]


class AuthVerify(BaseModel):
    challenge: str
    credential: dict[str, Any]


class DevicePatch(BaseModel):
    label: str | None = None
    role: str | None = None


@router.get("/status")
def auth_status(request: Request) -> dict[str, Any]:
    cfg = get_auth_config()
    sess = _session_from_request(request)
    return {
        "mode": cfg.mode,
        "rp_id": cfg.rp_id,
        "origin": cfg.origin,
        "public_host": cfg.public_host,
        "bind_loopback_only": cfg.bind_loopback_only,
        "authenticated": bool(sess) or cfg.mode == "off",
        "role": (sess or {}).get("role") if sess else ("admin" if cfg.mode == "off" else None),
        "device_count": len(get_store().list_devices()),
    }


@router.post("/pair/request")
def pair_request(body: PairRequest, request: Request) -> dict[str, Any]:
    store = get_store()
    ip = request.client.host if request.client else "?"
    if not store.rate_hit(f"pair:{ip}", limit=8, window=300):
        _audit("auth_pair_request", outcome="denied", detail="rate")
        raise HTTPException(429, "too many pairing requests")
    soft = _soft(request)
    soft["device_name"] = body.device_name
    rec = store.create_pending(body.device_name, soft)
    _audit("auth_pair_request", detail=rec["id"])
    return {
        "pending_id": rec["id"],
        "code": rec["code"],
        "expires_in": int(rec["expires"] - time.time()),
        "soft": soft,
        "message": "Show this code to the owner on the PC. They must approve with a matching code.",
    }


@router.get("/pair/pending")
def pair_pending(request: Request) -> dict[str, Any]:
    require_session(request, min_role=Role.ADMIN)
    return {"pending": get_store().list_pending()}


@router.post("/pair/approve")
def pair_approve(body: PairApprove, request: Request) -> dict[str, Any]:
    require_session(request, min_role=Role.ADMIN)
    # Physical input gate — desktop agent must not be able to click Allow.
    try:
        from friday.safety.physical import check_physical, required

        # Force the check when pairing even if the global gate is off (D / Stage O).
        if get_auth_config().require_physical_for_pair:
            from friday.safety import physical as P

            was = P.required()
            import os

            os.environ["FRIDAY_REQUIRE_PHYSICAL_INPUT"] = "true"
            try:
                ok, why = check_physical(window=5.0)
            finally:
                if not was:
                    os.environ["FRIDAY_REQUIRE_PHYSICAL_INPUT"] = "false"
            if not ok:
                _audit("auth_pair_approve", outcome="denied", detail=why)
                raise HTTPException(403, f"physical confirmation required: {why}")
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        _audit("auth_pair_approve", outcome="error", detail=str(exc))
        raise HTTPException(403, f"physical confirmation unavailable: {exc}") from exc

    store = get_store()
    if not store.rate_hit("pair_approve", limit=20, window=300):
        raise HTTPException(429, "rate limited")
    out = store.approve_pending(body.pending_id, body.code)
    if not out:
        _audit("auth_pair_approve", outcome="denied", detail="code mismatch")
        raise HTTPException(400, "invalid pending request or code")
    _audit("auth_pair_approve", detail=body.pending_id)
    return {
        "enrollment_token": out["enrollment_token"],
        "expires_in": 300,
        "device_name": out["pending"]["device_name"],
    }


@router.post("/register/options")
def reg_options(request: Request, enrollment_token: str = "") -> dict[str, Any]:
    store = get_store()
    # First device on localhost may enroll without pairing (owner bootstrap).
    cfg = get_auth_config()
    token = enrollment_token or request.headers.get("x-enrollment-token", "")
    if not token and cfg.mode == "local" and not store.list_devices():
        token = "bootstrap"
        store.data.setdefault("enrollment", {})[token] = {
            "pending_id": "bootstrap",
            "device_name": "This PC",
            "expires": time.time() + 300,
            "used": False,
        }
        store.save()
    en = store.data.get("enrollment", {}).get(token)
    if not en or en.get("used") or en.get("expires", 0) < time.time():
        raise HTTPException(400, "valid enrollment token required")
    handle = secrets.token_hex(16)
    opts = WA.registration_options(user_handle=handle, user_name=en["device_name"])
    return {"options": opts, "user_handle": handle, "enrollment_token": token}


@router.post("/register/verify")
def reg_verify(body: RegVerify, response: Response) -> dict[str, Any]:
    store = get_store()
    en = store.peek_enrollment(body.enrollment_token)
    if not en:
        raise HTTPException(400, "enrollment token invalid or used")
    try:
        ch_meta = store.data.get("challenges", {}).get(body.challenge) or {}
        user_handle = ch_meta.get("user_handle") or secrets.token_hex(16)
        verified = WA.verify_registration(
            body.credential,
            expected_challenge=body.challenge,
            user_handle=user_handle,
        )
    except Exception as exc:  # noqa: BLE001
        _audit("auth_register", outcome="denied", detail=str(exc))
        raise HTTPException(400, f"registration failed: {exc}") from exc
    store.consume_enrollment(body.enrollment_token)
    role = Role.ADMIN if not store.list_devices() else Role.CHAT
    device = store.add_device(
        credential_id=verified["credential_id"],
        public_key=verified["public_key"],
        sign_count=verified["sign_count"],
        label=en["device_name"],
        role=role,
        user_handle=user_handle,
    )
    cfg = get_auth_config()
    sess = store.create_session(device["id"], device["role"], cfg.session_ttl_s)
    response.set_cookie(
        cfg.cookie_name,
        sess["id"],
        httponly=True,
        secure=cfg.origin.startswith("https://"),
        samesite="strict",
        max_age=cfg.session_ttl_s,
        path="/",
    )
    _audit("auth_register", detail=device["id"])
    return {"device_id": device["id"], "role": device["role"], "label": device["label"]}


@router.post("/login/options")
def login_options() -> dict[str, Any]:
    if not get_store().list_devices() and get_auth_config().mode != "off":
        raise HTTPException(400, "no devices registered — pair or bootstrap first")
    return {"options": WA.authentication_options()}


@router.post("/login/verify")
def login_verify(body: AuthVerify, response: Response) -> dict[str, Any]:
    store = get_store()
    ip = "login"
    if not store.rate_hit(ip, limit=15, window=60):
        raise HTTPException(429, "too many login attempts")
    try:
        device = WA.verify_authentication(body.credential, expected_challenge=body.challenge)
    except Exception as exc:  # noqa: BLE001
        _audit("auth_login", outcome="denied", detail=str(exc))
        raise HTTPException(401, f"login failed: {exc}") from exc
    cfg = get_auth_config()
    sess = store.create_session(device["id"], device["role"], cfg.session_ttl_s)
    response.set_cookie(
        cfg.cookie_name,
        sess["id"],
        httponly=True,
        secure=cfg.origin.startswith("https://"),
        samesite="strict",
        max_age=cfg.session_ttl_s,
        path="/",
    )
    _audit("auth_login", detail=device["id"])
    return {"device_id": device["id"], "role": device["role"], "label": device["label"]}


@router.post("/logout")
def logout(request: Request, response: Response) -> dict[str, str]:
    cfg = get_auth_config()
    sid = request.cookies.get(cfg.cookie_name)
    if sid:
        get_store().delete_session(sid)
    response.delete_cookie(cfg.cookie_name, path="/")
    return {"ok": "logged out"}


@router.post("/stepup/options")
def stepup_options(request: Request) -> dict[str, Any]:
    sess = require_session(request, min_role=Role.TOOLS)
    device = None
    for d in get_store().list_devices():
        if d["id"] == sess.get("device_id"):
            device = d
            break
    return {"options": WA.authentication_options(device=device)}


@router.post("/stepup/verify")
def stepup_verify(body: AuthVerify, request: Request) -> dict[str, Any]:
    sess = require_session(request, min_role=Role.TOOLS)
    try:
        WA.verify_authentication(body.credential, expected_challenge=body.challenge)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(401, f"step-up failed: {exc}") from exc
    get_store().mark_stepup(sess["id"], ttl=60)
    _audit("auth_stepup", detail=sess["id"])
    return {"ok": True, "valid_for_s": 60}


@router.get("/devices")
def devices(request: Request) -> dict[str, Any]:
    require_session(request, min_role=Role.ADMIN)
    rows = []
    for d in get_store().list_devices():
        rows.append({
            "id": d["id"],
            "label": d["label"],
            "role": d["role"],
            "created": d["created"],
            "last_used": d["last_used"],
        })
    return {"devices": rows}


@router.patch("/devices/{device_id}")
def patch_device(device_id: str, body: DevicePatch, request: Request) -> dict[str, Any]:
    require_stepup(request)
    store = get_store()
    d = store.update_device(
        device_id,
        label=body.label,
        role=parse_role(body.role).value if body.role else None,
    )
    if not d:
        raise HTTPException(404, "device not found")
    _audit("auth_device_patch", detail=device_id, args={"role": body.role, "label": body.label})
    return {"id": d["id"], "label": d["label"], "role": d["role"]}


@router.delete("/devices/{device_id}")
def revoke_device(device_id: str, request: Request) -> dict[str, Any]:
    require_stepup(request)
    if not get_store().revoke_device(device_id):
        raise HTTPException(404, "device not found")
    _audit("auth_device_revoke", detail=device_id)
    return {"revoked": device_id}
