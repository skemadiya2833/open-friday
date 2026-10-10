"""Request guard for the Control Center API.

Controls (pure ASGI, applied to HTTP and WebSocket):
1. Host allow-list — exact configured hosts (no RFC1918 relaxation when auth/remote is on).
2. Origin check — must match this server's origin or an explicit extra origin.
3. Session cookie (passkey login) or optional FRIDAY_API_TOKEN for scripts.
4. Role gate for API classes (chat / tools / desktop / admin).
"""

from __future__ import annotations

import hmac
from typing import Iterable
from urllib.parse import urlsplit

_SAFE_METHODS = {"GET", "HEAD"}

# Paths that do not need a session (static UI + auth ceremony).
_PUBLIC_PREFIXES = (
    "/api/auth/status",
    "/api/auth/pair/request",
    "/api/auth/register/",
    "/api/auth/login/",
    "/api/health",
    "/health",
    "/favicon",
)
_PUBLIC_EXACT = {"/", "/index.html", "/app.js", "/styles.css", "/live.js", "/tools.js"}
_STATIC_SUFFIXES = (".js", ".css", ".map", ".svg", ".png", ".ico", ".woff2", ".html")


def _hostname(hostport: str) -> str:
    hostport = hostport.strip().lower()
    if hostport.startswith("["):
        end = hostport.find("]")
        return hostport[: end + 1] if end != -1 else hostport
    return hostport.rsplit(":", 1)[0] if ":" in hostport else hostport


def is_loopback(host: str) -> bool:
    h = host.strip().lower().strip("[]")
    return h in {"127.0.0.1", "localhost", "::1"}


def local_ipv4s() -> list[str]:
    import socket

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
    """Exact hostnames only. Private LAN IPs are NOT included unless listed in extra / public host."""
    hosts = {"127.0.0.1", "localhost", "[::1]"}
    try:
        from friday.auth.config import get_auth_config

        cfg = get_auth_config()
        if cfg.public_host:
            hosts.add(cfg.public_host.lower())
        hosts.add(cfg.rp_id.lower())
    except Exception:  # noqa: BLE001
        pass
    hosts.update(h.strip().lower() for h in extra if h and h.strip())
    return hosts


def _public_path(path: str) -> bool:
    if path in _PUBLIC_EXACT:
        return True
    for p in _PUBLIC_PREFIXES:
        if path == p or path.startswith(p):
            return True
    if any(path.endswith(s) for s in _STATIC_SUFFIXES) and not path.startswith("/api/"):
        return True
    return False


def _min_role_for(path: str, method: str) -> str | None:
    """Return required role name, or None if public/unauthenticated ok when auth off."""
    if _public_path(path):
        return None
    if path.startswith("/api/auth/devices") or path.startswith("/api/auth/pair/approve") or path.startswith("/api/auth/pair/pending"):
        return "admin"
    if path.startswith("/api/auth/stepup"):
        return "tools"
    if path.startswith("/api/agent") or path.startswith("/api/runs") or path.startswith("/api/estop"):
        return "desktop-control"
    if path.startswith("/api/tools") or path.startswith("/api/mcp") or path.startswith("/api/approvals"):
        return "tools"
    if method not in _SAFE_METHODS and path.startswith("/api/"):
        return "chat"
    if path.startswith("/api/"):
        return "chat"
    return "chat"


class RequestGuard:
    def __init__(
        self,
        app,
        *,
        allowed_hosts: set[str],
        token: str | None = None,
        extra_origins: Iterable[str] = (),
    ) -> None:
        self.app = app
        self.allowed_hosts = {h.lower() for h in allowed_hosts}
        self.token = token or None
        self.extra_origins = {o.strip().lower().rstrip("/") for o in extra_origins if o and o.strip()}

    @staticmethod
    def _header(scope, name: bytes) -> str:
        for k, v in scope.get("headers", []):
            if k == name:
                return v.decode("latin-1")
        return ""

    def _cookies(self, scope) -> dict[str, str]:
        raw = self._header(scope, b"cookie")
        out: dict[str, str] = {}
        for part in raw.split(";"):
            if "=" in part:
                k, v = part.split("=", 1)
                out[k.strip()] = v.strip()
        return out

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
        if parts.netloc.lower() != host.lower():
            return False
        return name in self.allowed_hosts

    def _token_ok(self, scope) -> bool:
        if not self.token:
            return False
        auth = self._header(scope, b"authorization")
        supplied = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
        if not supplied:
            qs = scope.get("query_string", b"").decode("latin-1")
            for pair in qs.split("&"):
                if pair.startswith("token="):
                    supplied = pair[6:]
        if not supplied:
            return False
        return hmac.compare_digest(supplied.encode(), self.token.encode())

    def _session_ok(self, scope, min_role: str) -> bool:
        try:
            from friday.auth.config import get_auth_config
            from friday.auth.roles import role_at_least
            from friday.auth.store import get_store

            cfg = get_auth_config()
            if cfg.mode == "off":
                return True
            sid = self._cookies(scope).get(cfg.cookie_name)
            if not sid:
                return False
            sess = get_store().get_session(sid)
            if not sess:
                return False
            return role_at_least(sess.get("role", "chat"), min_role)
        except Exception:  # noqa: BLE001
            return False

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
        if name not in self.allowed_hosts:
            return await self._deny(scope, receive, send, 403, "host not allowed")

        origin = self._header(scope, b"origin")
        method = scope.get("method", "GET").upper()
        path = scope.get("path") or "/"

        if scope["type"] == "websocket" or method not in _SAFE_METHODS:
            if origin and not self._origin_ok(origin, host):
                return await self._deny(scope, receive, send, 403, "cross-origin request blocked")
        elif origin and not self._origin_ok(origin, host):
            return await self._deny(scope, receive, send, 403, "cross-origin request blocked")

        # Authn
        try:
            from friday.auth.config import get_auth_config

            auth_mode = get_auth_config().mode
        except Exception:  # noqa: BLE001
            auth_mode = "off"

        min_role = _min_role_for(path, method)
        if min_role is not None:
            if auth_mode != "off":
                if not (self._session_ok(scope, min_role) or self._token_ok(scope)):
                    return await self._deny(scope, receive, send, 401, "authentication required")
            elif self.token and not self._token_ok(scope):
                # Auth off but token configured: scripts must send bearer for API routes.
                return await self._deny(scope, receive, send, 401, "missing or invalid token")

        await self.app(scope, receive, send)


# Kept for older imports / tests that still reference private-hostname helpers.
def is_private_hostname(host: str) -> bool:
    """Deprecated: private IPs are no longer accepted as Host by default."""
    import ipaddress

    h = _hostname(host).strip("[]")
    if is_loopback(h):
        return True
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return False
    return bool(ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_unspecified)
