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
import ipaddress
import socket
from typing import Iterable
from urllib.parse import urlsplit

_SAFE_METHODS = {"GET", "HEAD"}


def _hostname(hostport: str) -> str:
    hostport = hostport.strip().lower()
    if hostport.startswith("["):                       # [::1]:8787
        end = hostport.find("]")
        return hostport[: end + 1] if end != -1 else hostport
    return hostport.rsplit(":", 1)[0] if ":" in hostport else hostport


def is_loopback(host: str) -> bool:
    h = host.strip().lower().strip("[]")
    return h in {"127.0.0.1", "localhost", "::1"}


def is_private_hostname(host: str) -> bool:
    """Loopback, unspecified, or RFC1918 / link-local — safe Host values on the home LAN."""
    h = _hostname(host).strip("[]")
    if is_loopback(h):
        return True
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return False
    return bool(ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_unspecified)


def local_ipv4s() -> list[str]:
    found: list[str] = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip and not ip.startswith("127."):
                found.append(ip)
    except OSError:
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("1.1.1.1", 80))
            ip = s.getsockname()[0]
            if ip and not ip.startswith("127."):
                found.append(ip)
    except OSError:
        pass
    return list(dict.fromkeys(found))


def default_allowed_hosts(extra: Iterable[str] = ()) -> set[str]:
    """Allowed *hostnames* (ports are not part of the DNS-rebinding defence)."""
    hosts = {"127.0.0.1", "localhost", "[::1]", "0.0.0.0"}
    hosts.update(local_ipv4s())
    hosts.update(h.strip().lower() for h in extra if h and h.strip())
    return hosts


class RequestGuard:
    def __init__(
        self, app, *, allowed_hosts: set[str], token: str | None = None, extra_origins: Iterable[str] = ()
    ) -> None:
        self.app = app
        self.allowed_hosts = {h.lower() for h in allowed_hosts}
        self.token = token or None
        # Exact origins (scheme://host:port) trusted in addition to same-origin, e.g. the
        # Vite dev server, whose proxy rewrites Host to the backend but keeps its own Origin.
        self.extra_origins = {o.strip().lower().rstrip("/") for o in extra_origins if o and o.strip()}

    @staticmethod
    def _header(scope, name: bytes) -> str:
        for k, v in scope.get("headers", []):
            if k == name:
                return v.decode("latin-1")
        return ""

    def _origin_ok(self, origin: str, host: str) -> bool:
        if origin.strip().lower().rstrip("/") in self.extra_origins:
            return True
        try:
            parts = urlsplit(origin)
        except ValueError:
            return False
        if parts.scheme not in ("http", "https") or not parts.netloc:
            return False
        name = _hostname(host)
        return parts.netloc.lower() == host.lower() and (
            name in self.allowed_hosts or is_private_hostname(name)
        )

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
        name = _hostname(host)
        if name not in self.allowed_hosts and not is_private_hostname(name):
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
