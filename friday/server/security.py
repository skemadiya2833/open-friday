"""Request guard for the Control Center API.

Threat: any web page the owner visits can send requests to http://127.0.0.1:<port>
(CSRF / DNS rebinding) and, via the API, make Friday drive the desktop or approve its
own tool prompts. The previous server answered every origin (`allow_origins=["*"]`).

Controls (pure ASGI, applied to HTTP and WebSocket):
1. Host allow-list  -> defeats DNS rebinding (attacker hostname resolving to 127.0.0.1).
2. Origin check     -> browsers always attach Origin to cross-origin POST/PUT/PATCH/DELETE
                       and to WebSocket handshakes; it must equal this server's own origin.
                       Requests without Origin (curl, tests, native clients) are allowed
                       by (1)+(3) only.
3. Bearer token     -> mandatory when the server is bound to a non-loopback address.
No CORS headers are emitted at all: the UI is same-origin.
"""

from __future__ import annotations

import hmac
from typing import Iterable
from urllib.parse import urlsplit

_SAFE_METHODS = {"GET", "HEAD"}


def default_allowed_hosts(extra: Iterable[str] = ()) -> set[str]:
    """Allowed *hostnames* (ports are not part of the DNS-rebinding defence)."""
    hosts = {"127.0.0.1", "localhost", "[::1]"}
    hosts.update(h.strip().lower() for h in extra if h and h.strip())
    return hosts


def _hostname(hostport: str) -> str:
    hostport = hostport.strip().lower()
    if hostport.startswith("["):                       # [::1]:8787
        end = hostport.find("]")
        return hostport[: end + 1] if end != -1 else hostport
    return hostport.rsplit(":", 1)[0] if ":" in hostport else hostport


def is_loopback(host: str) -> bool:
    return host in {"127.0.0.1", "localhost", "::1", "[::1]"}


class RequestGuard:
    def __init__(self, app, *, allowed_hosts: set[str], token: str | None = None) -> None:
        self.app = app
        self.allowed_hosts = {h.lower() for h in allowed_hosts}
        self.token = token or None

    @staticmethod
    def _header(scope, name: bytes) -> str:
        for k, v in scope.get("headers", []):
            if k == name:
                return v.decode("latin-1")
        return ""

    def _origin_ok(self, origin: str, host: str) -> bool:
        try:
            parts = urlsplit(origin)
        except ValueError:
            return False
        if parts.scheme not in ("http", "https") or not parts.netloc:
            return False
        return parts.netloc.lower() == host.lower() and _hostname(host) in self.allowed_hosts

    def _token_ok(self, scope) -> bool:
        if not self.token:
            return True
        auth = self._header(scope, b"authorization")
        supplied = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
        if not supplied:
            qs = scope.get("query_string", b"").decode("latin-1")
            for pair in qs.split("&"):
                if pair.startswith("token="):
                    supplied = pair[6:]
        return hmac.compare_digest(supplied.encode(), self.token.encode())

    async def _deny(self, scope, receive, send, status: int, reason: str) -> None:
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008, "reason": reason})
            return
        body = f'{{"detail":"{reason}"}}'.encode()
        await send({
            "type": "http.response.start", "status": status,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
        })
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)

        host = self._header(scope, b"host").lower()
        if _hostname(host) not in self.allowed_hosts:
            return await self._deny(scope, receive, send, 403, "host not allowed")

        origin = self._header(scope, b"origin")
        method = scope.get("method", "GET").upper()
        if scope["type"] == "websocket" or method not in _SAFE_METHODS:
            if origin and not self._origin_ok(origin, host):
                return await self._deny(scope, receive, send, 403, "cross-origin request blocked")
        elif origin and not self._origin_ok(origin, host):
            # Cross-origin GET: blocked too (no CORS is granted, and some GETs are cheap probes).
            return await self._deny(scope, receive, send, 403, "cross-origin request blocked")

        if not self._token_ok(scope):
            return await self._deny(scope, receive, send, 401, "missing or invalid token")

        await self.app(scope, receive, send)
