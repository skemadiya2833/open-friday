"""Request guard + Control Center API, against the real FastAPI app."""

from __future__ import annotations

import threading
import time

import pytest
from fastapi.testclient import TestClient

from friday.server.app import app
from friday.safety.approval import get_approval_service

H = {"host": "127.0.0.1:8787"}


@pytest.fixture()
def client(isolated):
    with TestClient(app, base_url="http://127.0.0.1:8787") as c:
        yield c


def test_no_cors_wildcard(client):
    r = client.get("/api/tools", headers={**H, "Origin": "http://evil.example"})
    assert r.status_code == 403
    assert "access-control-allow-origin" not in r.headers


def test_dns_rebinding_host_rejected(client):
    r = client.get("/api/tools", headers={"host": "evil.example:8787"})
    assert r.status_code == 403


def test_lan_ip_host_is_rejected_without_public_hostname(client):
    """Stage O: private IP Host values are no longer allowed (need FRIDAY_PUBLIC_HOST)."""
    r = client.get("/api/health", headers={"host": "192.168.1.24:8787"})
    assert r.status_code == 403
    r = client.post("/api/sessions", headers={"host": "192.168.1.24:8787", "Origin": "http://192.168.1.24:8787"})
    assert r.status_code == 403


def test_cross_origin_post_rejected_and_preflight_rejected(client):
    r = client.post("/api/mcp/kill", headers={**H, "Origin": "http://evil.example"})
    assert r.status_code == 403
    r = client.options("/api/mcp/kill", headers={**H, "Origin": "http://evil.example",
                                                  "Access-Control-Request-Method": "POST"})
    assert r.status_code == 403


def test_same_origin_post_allowed(client):
    r = client.post("/api/mcp/kill", headers={**H, "Origin": "http://127.0.0.1:8787"})
    assert r.status_code == 200


def test_cross_origin_websocket_rejected(client):
    with pytest.raises(Exception):
        with client.websocket_connect("/ws", headers={**H, "Origin": "http://evil.example"}):
            pass


def test_tools_policy_audit_endpoints(client):
    assert any(t["name"] == "read_file" for t in client.get("/api/tools").json()["tools"])
    assert client.get("/api/policy").json()["tiers"]["dangerous"] == "deny"
    a = client.get("/api/audit").json()
    assert a["chain_ok"] is True


def test_approval_roundtrip_over_http(client):
    svc = get_approval_service()
    result: dict = {}

    def ask():
        result["v"] = svc.request(tool="write_file", args={"path": "x"}, risk="confirm", caller="test", timeout=10)

    client.get("/api/approvals")  # marks a human as present
    t = threading.Thread(target=ask)
    t.start()
    pending = []
    for _ in range(50):
        pending = client.get("/api/approvals").json()["pending"]
        if pending:
            break
        time.sleep(0.1)
    assert pending and pending[0]["tool"] == "write_file"
    url = f"/api/approvals/{pending[0]['id']}"
    # A bare script (no Origin / Sec-Fetch-Site) cannot grant.
    assert client.post(url, json={"approved": True}).status_code == 403
    assert client.post(url, json={"approved": True}, headers={**H, "Origin": "http://127.0.0.1:8787"}).status_code == 403
    assert svc.list_pending(), "still pending after refused grants"
    ui = {**H, "Origin": "http://127.0.0.1:8787", "Sec-Fetch-Site": "same-origin"}
    assert client.post(url, json={"approved": True}, headers=ui).status_code == 200
    t.join(5)
    assert result["v"][0] is True
    assert client.post("/api/approvals/nope", json={"approved": True}, headers=ui).status_code == 404


def test_token_is_script_fallback_for_api(monkeypatch):
    """FRIDAY_API_TOKEN is optional for scripts; UI static stays public; API needs session or token when auth on."""
    from friday.auth.config import reset_auth_config
    from friday.server.security import RequestGuard, default_allowed_hosts

    monkeypatch.setenv("FRIDAY_AUTH", "local")
    reset_auth_config()

    async def inner(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    c = TestClient(RequestGuard(inner, allowed_hosts=default_allowed_hosts(), token="s3cret"),
                   base_url="http://127.0.0.1:1")
    assert c.get("/").status_code == 200  # static public
    assert c.get("/api/tools").status_code == 401
    assert c.get("/api/tools", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert c.get("/api/tools", headers={"Authorization": "Bearer s3cret"}).status_code == 200
    monkeypatch.setenv("FRIDAY_AUTH", "off")
    reset_auth_config()


def test_polling_only_script_cannot_approve(client):
    """Polling /api/approvals marks presence (prompt waits) but a prompt nobody answers is denied."""
    svc = get_approval_service()
    svc.default_timeout = 1.0
    result: dict = {}

    def ask():
        result["v"] = svc.request(tool="write_file", args={"p": 1}, risk="confirm", caller="t", timeout=1.5)

    client.get("/api/approvals")
    t = threading.Thread(target=ask)
    t.start()
    end = time.time() + 3
    while time.time() < end and t.is_alive():
        client.get("/api/approvals")   # polling only
        time.sleep(0.1)
    t.join(5)
    assert result["v"][0] is False
    assert "timeout" in result["v"][1] or "denied" in result["v"][1]


def test_no_responder_fails_closed_without_polling(client):
    svc = get_approval_service()
    assert svc.request(tool="write_file", args={}, risk="confirm", caller="t", timeout=1)[0] is False


def test_extra_origin_allowed_only_when_configured():
    """Vite dev proxy: Host is rewritten to the backend, Origin stays the dev server's."""
    from friday.server.security import RequestGuard, default_allowed_hosts

    async def inner(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    hdr = {"Origin": "http://localhost:5173"}
    strict = TestClient(RequestGuard(inner, allowed_hosts=default_allowed_hosts()), base_url="http://127.0.0.1:8787")
    assert strict.post("/x", headers=hdr).status_code == 403
    dev = TestClient(
        RequestGuard(inner, allowed_hosts=default_allowed_hosts(), extra_origins=["http://localhost:5173"]),
        base_url="http://127.0.0.1:8787",
    )
    assert dev.post("/x", headers=hdr).status_code == 200
    assert dev.post("/x", headers={"Origin": "http://localhost:5174"}).status_code == 403
    assert dev.post("/x", headers={"Origin": "http://evil.example"}).status_code == 403


def test_lan_firewall_rule_is_private_tcp_8787():
    from friday.server.lan import add_rule_args, rule_name

    args = add_rule_args(8787)
    assert rule_name(8787) in " ".join(args)
    assert "localport=8787" in args and "profile=private" in args and "dir=in" in args
    assert rule_name(8788) != rule_name(8787)
