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
    assert client.post(f"/api/approvals/{pending[0]['id']}", json={"approved": True}).status_code == 200
    t.join(5)
    assert result["v"][0] is True
    assert client.post("/api/approvals/nope", json={"approved": True}).status_code == 404


def test_token_required_when_configured():
    from friday.server.security import RequestGuard, default_allowed_hosts

    async def inner(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    c = TestClient(RequestGuard(inner, allowed_hosts=default_allowed_hosts(), token="s3cret"),
                   base_url="http://127.0.0.1:1")
    assert c.get("/").status_code == 401
    assert c.get("/", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert c.get("/", headers={"Authorization": "Bearer s3cret"}).status_code == 200
