"""WebAuthn registration and authentication via the ``webauthn`` (py_webauthn) package."""

from __future__ import annotations

import json
from typing import Any

from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.structs import (
    AttestationConveyancePreference,
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from friday.auth.config import AuthConfig, get_auth_config
from friday.auth.store import AuthStore, get_store


def registration_options(*, user_handle: str, user_name: str, cfg: AuthConfig | None = None) -> dict[str, Any]:
    cfg = cfg or get_auth_config()
    store = get_store()
    opts = generate_registration_options(
        rp_id=cfg.rp_id,
        rp_name=cfg.rp_name,
        user_id=user_handle.encode("utf-8"),
        user_name=user_name,
        user_display_name=user_name,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        attestation=AttestationConveyancePreference.NONE,
    )
    challenge = bytes_to_base64url(opts.challenge)
    store.put_challenge("reg", user_handle, challenge)
    return json.loads(options_to_json(opts))


def verify_registration(
    credential: dict[str, Any],
    *,
    expected_challenge: str,
    user_handle: str,
    cfg: AuthConfig | None = None,
) -> dict[str, Any]:
    cfg = cfg or get_auth_config()
    store = get_store()
    ch = store.take_challenge(expected_challenge, "reg")
    if not ch or ch.get("user_handle") != user_handle:
        raise ValueError("challenge invalid or expired")
    verification = verify_registration_response(
        credential=credential,
        expected_challenge=base64url_to_bytes(expected_challenge),
        expected_rp_id=cfg.rp_id,
        expected_origin=cfg.origin,
        require_user_verification=True,
    )
    if not verification.user_verified:
        raise ValueError("user verification required")
    return {
        "credential_id": bytes_to_base64url(verification.credential_id),
        "public_key": bytes_to_base64url(verification.credential_public_key),
        "sign_count": int(verification.sign_count),
    }


def authentication_options(*, cfg: AuthConfig | None = None, device: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = cfg or get_auth_config()
    store = get_store()
    allow: list[PublicKeyCredentialDescriptor] = []
    if device:
        allow = [
            PublicKeyCredentialDescriptor(id=base64url_to_bytes(device["credential_id"]))
        ]
    else:
        for d in store.list_devices():
            allow.append(PublicKeyCredentialDescriptor(id=base64url_to_bytes(d["credential_id"])))
    opts = generate_authentication_options(
        rp_id=cfg.rp_id,
        allow_credentials=allow or None,
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    challenge = bytes_to_base64url(opts.challenge)
    store.put_challenge("auth", device["id"] if device else "*", challenge)
    return json.loads(options_to_json(opts))


def verify_authentication(
    credential: dict[str, Any],
    *,
    expected_challenge: str,
    cfg: AuthConfig | None = None,
) -> dict[str, Any]:
    cfg = cfg or get_auth_config()
    store = get_store()
    ch = store.take_challenge(expected_challenge, "auth")
    if not ch:
        raise ValueError("challenge invalid or expired")
    cred_id = credential.get("id") or credential.get("rawId")
    if not cred_id:
        raise ValueError("missing credential id")
    device = store.device_by_credential(cred_id)
    if not device:
        raise ValueError("unknown device")
    verification = verify_authentication_response(
        credential=credential,
        expected_challenge=base64url_to_bytes(expected_challenge),
        expected_rp_id=cfg.rp_id,
        expected_origin=cfg.origin,
        credential_public_key=base64url_to_bytes(device["public_key"]),
        credential_current_sign_count=int(device.get("sign_count") or 0),
        require_user_verification=True,
    )
    if not verification.user_verified:
        raise ValueError("user verification required")
    new_count = int(verification.new_sign_count)
    if new_count <= int(device.get("sign_count") or 0) and int(device.get("sign_count") or 0) > 0:
        raise ValueError("sign counter did not advance (possible cloned authenticator)")
    store.update_device(device["id"], sign_count=new_count, last_used=__import__("time").time())
    return device
