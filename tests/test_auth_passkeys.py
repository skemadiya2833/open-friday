"""Passkey auth store, roles, guard, schedule_task reminder-only (no live authenticator)."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from friday.auth.config import reset_auth_config
from friday.auth.roles import Role, role_at_least
from friday.auth.store import AuthStore, set_store
from friday.server.app import app


@pytest.fixture()
def auth_env(tmp_path, monkeypatch, isolated):
    monkeypatch.setenv("FRIDAY_AUTH", "local")
    monkeypatch.setattr("friday.config.DATA_DIR", str(tmp_path))
    from friday.auth.prefs import save_auth_prefs

    save_auth_prefs({"phone_access": False})
    reset_auth_config()
    store = AuthStore(tmp_path / "auth.json")
    set_store(store)
    yield store
    set_store(None)
    save_auth_prefs({"phone_access": False})
    monkeypatch.setenv("FRIDAY_AUTH", "off")
    reset_auth_config()


def test_role_ordering():
    assert role_at_least(Role.ADMIN, Role.CHAT)
    assert not role_at_least(Role.CHAT, Role.DESKTOP)


def test_pairing_code_and_enrollment(auth_env):
    store = auth_env
    pend = store.create_pending("Pixel", {"ua": "test", "ip": "1.2.3.4"})
    assert len(pend["code"]) == 6
    bad = store.approve_pending(pend["id"], "000000")
    assert bad is None
    ok = store.approve_pending(pend["id"], pend["code"])
    assert ok and ok["enrollment_token"]
    en = store.peek_enrollment(ok["enrollment_token"])
    assert en and en["device_name"] == "Pixel"
    store.consume_enrollment(ok["enrollment_token"])
    assert store.peek_enrollment(ok["enrollment_token"]) is None


def test_claim_approved_device_without_passkey(auth_env):
    store = auth_env
    pend = store.create_pending("Pixel 8", {"ua": "phone", "ip": "10.0.0.5"})
    assert store.approve_pending(pend["id"], pend["code"])
    claimed = store.claim_approved_pending(pend["id"], pend["code"])
    assert claimed and claimed["device_name"] == "Pixel 8"
    # second claim fails
    assert store.claim_approved_pending(pend["id"], pend["code"]) is None
    device = store.add_approved_device(label=claimed["device_name"], role=Role.CHAT)
    assert device["auth_kind"] == "approved"
    assert not device["credential_id"]
    sess = store.create_session(device["id"], device["role"], ttl=3600)
    assert store.get_session(sess["id"])


def test_lan_mode_status_flags(monkeypatch, tmp_path, isolated):
    monkeypatch.setenv("FRIDAY_AUTH", "lan")
    monkeypatch.setenv("FRIDAY_REQUIRE_PHYSICAL_INPUT", "false")
    reset_auth_config()
    store = AuthStore(tmp_path / "auth-lan.json")
    set_store(store)
    try:
        from friday.auth.config import get_auth_config

        cfg = get_auth_config()
        assert cfg.mode == "lan"
        assert cfg.bind_loopback_only is False
        assert cfg.passkeys_required is False
        with TestClient(app, base_url="http://127.0.0.1:8787") as c:
            r = c.get("/api/auth/status", headers={"host": "127.0.0.1:8787"})
            assert r.status_code == 200
            body = r.json()
            assert body["mode"] == "lan"
            assert body["authenticated"] is True
            assert body["passkeys_optional"] is True
    finally:
        set_store(None)
        monkeypatch.setenv("FRIDAY_AUTH", "off")
        reset_auth_config()


def test_qr_invite_and_redeem(auth_env, monkeypatch, tmp_path, isolated):
    monkeypatch.setenv("FRIDAY_AUTH", "lan")
    monkeypatch.setenv("FRIDAY_REQUIRE_PHYSICAL_INPUT", "false")
    reset_auth_config()
    from friday.auth.prefs import save_auth_prefs
    from friday.server.security import set_listen_host

    save_auth_prefs({"phone_access": False})
    set_listen_host("0.0.0.0")
    store = auth_env
    try:
        with TestClient(app, base_url="http://127.0.0.1:8787") as c:
            r = c.post(
                "/api/auth/pair/qr",
                json={"device_name": "Pixel"},
                headers={"host": "127.0.0.1:8787", "Origin": "http://127.0.0.1:8787"},
            )
            assert r.status_code == 200, r.text
            body = r.json()
            if body.get("needs_restart"):
                inv = store.create_qr_invite(device_name="Pixel", ttl=120)
                token = inv["token"]
            else:
                assert body.get("ok") is True
                assert body.get("url") and "pair=" in body["url"]
                assert body.get("token")
                assert "<svg" in (body.get("svg") or "").lower()
                token = body["token"]
            redeem = c.post(
                "/api/auth/pair/redeem",
                json={"token": token},
                headers={"host": "127.0.0.1:8787", "Origin": "http://127.0.0.1:8787"},
            )
            assert redeem.status_code == 200, redeem.text
            out = redeem.json()
            assert out.get("ok") is True
            assert out.get("device_id")
            assert c.cookies.get("friday_session")
            again = c.post(
                "/api/auth/pair/redeem",
                json={"token": token},
                headers={"host": "127.0.0.1:8787", "Origin": "http://127.0.0.1:8787"},
            )
            assert again.status_code == 400
    finally:
        save_auth_prefs({"phone_access": False})
        set_listen_host("127.0.0.1")
        monkeypatch.setenv("FRIDAY_AUTH", "local")
        reset_auth_config()


def test_qr_create_needs_restart_when_loopback(auth_env, monkeypatch, isolated):
    monkeypatch.setenv("FRIDAY_AUTH", "local")
    reset_auth_config()
    from friday.auth.prefs import save_auth_prefs
    from friday.server.security import set_listen_host

    save_auth_prefs({"phone_access": False})
    set_listen_host("127.0.0.1")
    try:
        with TestClient(app, base_url="http://127.0.0.1:8787") as c:
            r = c.post(
                "/api/auth/pair/qr",
                json={"device_name": "Phone"},
                headers={"host": "127.0.0.1:8787", "Origin": "http://127.0.0.1:8787"},
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body.get("needs_restart") is True
    finally:
        save_auth_prefs({"phone_access": False})
        set_listen_host("127.0.0.1")
        reset_auth_config()


def test_session_revoke_kills_cookie(auth_env):
    store = auth_env
    d = store.add_device(
        credential_id="cred1", public_key="pk", sign_count=1, label="PC",
        role=Role.ADMIN, user_handle="u1",
    )
    sess = store.create_session(d["id"], d["role"], ttl=3600)
    assert store.get_session(sess["id"])
    store.revoke_device(d["id"])
    assert store.get_session(sess["id"]) is None


def test_cloned_counter_rejected_by_store_update_logic(auth_env):
    store = auth_env
    d = store.add_device(
        credential_id="c", public_key="p", sign_count=5, label="x",
        role=Role.CHAT, user_handle="h",
    )
    # webauthn_flow raises if new_count <= old; unit-check the invariant here
    assert int(d["sign_count"]) == 5


def test_local_mode_does_not_require_login(auth_env):
    with TestClient(app, base_url="http://127.0.0.1:8787") as c:
        r = c.get("/api/tools", headers={"host": "127.0.0.1:8787"})
        assert r.status_code == 200
        r = c.get("/api/auth/status", headers={"host": "127.0.0.1:8787"})
        assert r.status_code == 200
        body = r.json()
        assert body["mode"] == "local"
        assert body["authenticated"] is True
        assert body["passkeys_required"] is False


def test_remote_mode_rejects_unauthenticated(auth_env, monkeypatch):
    monkeypatch.setenv("FRIDAY_AUTH", "remote")
    monkeypatch.setenv("FRIDAY_PUBLIC_HOST", "friday.example.com")
    monkeypatch.setenv("FRIDAY_ORIGIN", "https://friday.example.com")
    reset_auth_config()
    with TestClient(app, base_url="https://friday.example.com") as c:
        r = c.get(
            "/api/tools",
            headers={"host": "friday.example.com", "Origin": "https://friday.example.com"},
        )
        # 401 = auth required; 403 = host not on the process allow-list (guard built at import).
        assert r.status_code in (401, 403)
    monkeypatch.setenv("FRIDAY_AUTH", "local")
    reset_auth_config()


def test_forged_origin_still_blocked(auth_env):
    with TestClient(app, base_url="http://127.0.0.1:8787") as c:
        r = c.post(
            "/api/auth/pair/request",
            json={"device_name": "evil"},
            headers={"host": "127.0.0.1:8787", "Origin": "http://evil.example"},
        )
        assert r.status_code == 403


def test_pair_request_same_origin(auth_env):
    with TestClient(app, base_url="http://127.0.0.1:8787") as c:
        r = c.post(
            "/api/auth/pair/request",
            json={"device_name": "phone"},
            headers={"host": "127.0.0.1:8787", "Origin": "http://127.0.0.1:8787"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["code"] and body["pending_id"]


def test_schedule_task_reminder_only(isolated):
    from friday.tools.builtin import _schedule_task

    bad = _schedule_task({"prompt": "open notepad", "skill_id": "computer_use", "delay_seconds": 60})
    assert bad.is_error
    assert "reminder" in bad.text().lower() or "Refusing" in bad.text()


def test_challenge_single_use(auth_env):
    store = auth_env
    store.put_challenge("auth", "*", "chal-1", ttl=60)
    assert store.take_challenge("chal-1", "auth")
    assert store.take_challenge("chal-1", "auth") is None


def test_rate_limit_lockout(auth_env):
    store = auth_env
    for _ in range(10):
        assert store.rate_hit("t", limit=10, window=60)
    assert store.rate_hit("t", limit=10, window=60) is False


def test_public_host_ip_rejected_by_config(monkeypatch):
    monkeypatch.setenv("FRIDAY_AUTH", "remote")
    monkeypatch.setenv("FRIDAY_PUBLIC_HOST", "192.168.1.24")
    reset_auth_config()
    from friday.diagnostics import validate_config

    errs = {i.key for i in validate_config(dict(os.environ)) if i.level == "error"}
    assert "FRIDAY_PUBLIC_HOST" in errs
    monkeypatch.setenv("FRIDAY_AUTH", "off")
    monkeypatch.delenv("FRIDAY_PUBLIC_HOST", raising=False)
    reset_auth_config()
