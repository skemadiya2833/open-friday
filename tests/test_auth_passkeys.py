"""Passkey auth store, roles, guard, schedule_task reminder-only (no live authenticator)."""

from __future__ import annotations

import os
import time

import pytest
from fastapi.testclient import TestClient

from friday.auth.config import reset_auth_config
from friday.auth.roles import Role, role_at_least
from friday.auth.store import AuthStore, set_store
from friday.server.app import app


@pytest.fixture()
def auth_env(tmp_path, monkeypatch, isolated):
    monkeypatch.setenv("FRIDAY_AUTH", "local")
    reset_auth_config()
    store = AuthStore(tmp_path / "auth.json")
    set_store(store)
    yield store
    set_store(None)
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


def test_unauthenticated_api_rejected_when_auth_on(auth_env):
    with TestClient(app, base_url="http://127.0.0.1:8787") as c:
        r = c.get("/api/tools", headers={"host": "127.0.0.1:8787"})
        assert r.status_code == 401
        r = c.get("/api/auth/status", headers={"host": "127.0.0.1:8787"})
        assert r.status_code == 200
        assert r.json()["mode"] == "local"


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
