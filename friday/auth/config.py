"""Auth / WebAuthn configuration.

Modes:
  off    — no auth (tests)
  local  — this PC only (loopback); no passkey login wall
  lan    — phone on same Wi‑Fi; owner approves devices; passkey optional
  remote — public hostname + passkeys required

LAN binds to all interfaces and allows local IPv4 Host headers. Passkeys remain
optional upgrades after approval.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import lru_cache

_IP = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")
_LOCAL = re.compile(r"\.local$", re.I)


@dataclass(frozen=True)
class AuthConfig:
    mode: str                       # off | local | lan | remote
    rp_id: str                      # localhost | friday.example.com
    rp_name: str
    origin: str                     # primary origin (cookie / docs)
    origins: tuple[str, ...]        # all accepted WebAuthn / CORS origins
    public_host: str                # empty until owner configures DNS+cert
    bind_loopback_only: bool
    session_ttl_s: int
    stepup_ttl_s: int
    enrollment_ttl_s: int
    cookie_name: str
    require_physical_for_pair: bool
    passkeys_required: bool


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def _valid_rp_id(host: str) -> bool:
    h = host.strip().lower()
    if not h or _IP.match(h) or _LOCAL.search(h) or ":" in h:
        return False
    if h == "localhost":
        return True
    # Registrable-looking domain: at least one dot, no spaces.
    return "." in h and " " not in h and not h.startswith(".")


@lru_cache(maxsize=1)
def get_auth_config() -> AuthConfig:
    mode = (_env("FRIDAY_AUTH", "local") or "local").lower()
    if mode not in ("off", "local", "lan", "remote"):
        mode = "local"
    # Devices → Show QR can enable phone access without editing .env (restart once).
    try:
        from friday.auth.prefs import phone_access_enabled

        if mode == "local" and phone_access_enabled():
            mode = "lan"
    except Exception:  # noqa: BLE001
        pass
    public = _env("FRIDAY_PUBLIC_HOST")
    http_port = int(_env("FRIDAY_PORT", "8787") or "8787")
    tls_port = int(_env("FRIDAY_TLS_PORT", "8788") or "8788")

    from friday.server.security import local_ipv4s

    lan_ips = local_ipv4s()

    if mode == "remote" and public and _valid_rp_id(public):
        rp_id = public.lower()
        origin = (_env("FRIDAY_ORIGIN") or f"https://{rp_id}").rstrip("/")
        origins = (origin,)
        bind_loopback = False
        passkeys_required = True
        phys_default = "true"
    elif mode == "lan":
        # Phone on Wi‑Fi: bind all interfaces; Host may be a LAN IP (no WebAuthn RP ID).
        rp_id = public.lower() if public and _valid_rp_id(public) else "localhost"
        primary_ip = lan_ips[0] if lan_ips else "127.0.0.1"
        origin = (_env("FRIDAY_ORIGIN") or f"http://{primary_ip}:{http_port}").rstrip("/")
        origins_list = [
            origin,
            f"http://localhost:{http_port}",
            f"http://127.0.0.1:{http_port}",
            f"https://localhost:{tls_port}",
            f"https://127.0.0.1:{tls_port}",
        ]
        for ip in lan_ips:
            origins_list.append(f"http://{ip}:{http_port}")
            origins_list.append(f"https://{ip}:{tls_port}")
        if public and _valid_rp_id(public):
            origins_list.append(f"https://{public}")
            origins_list.append(f"https://{public}:{tls_port}")
        origins = tuple(dict.fromkeys(origins_list))
        bind_loopback = False
        passkeys_required = False
        phys_default = "false"  # owner click on PC is enough for home LAN
    elif mode == "off":
        rp_id = "localhost"
        origin = f"http://127.0.0.1:{http_port}"
        origins = (origin, f"http://localhost:{http_port}")
        bind_loopback = True
        passkeys_required = False
        phys_default = "true"
        public = ""
    else:
        # local: this PC, loopback bind, no login wall.
        mode = "local"
        rp_id = "localhost"
        origin = (_env("FRIDAY_ORIGIN") or f"http://localhost:{http_port}").rstrip("/")
        origins = tuple(dict.fromkeys([
            origin,
            f"http://localhost:{http_port}",
            f"http://127.0.0.1:{http_port}",
        ]))
        bind_loopback = True
        passkeys_required = False
        phys_default = "true"
        public = ""

    return AuthConfig(
        mode=mode,
        rp_id=rp_id,
        rp_name=_env("FRIDAY_RP_NAME", "Friday"),
        origin=origin,
        origins=origins,
        public_host=(public or "").lower(),
        bind_loopback_only=bind_loopback,
        session_ttl_s=int(_env("FRIDAY_SESSION_TTL", "86400") or "86400"),
        stepup_ttl_s=60,
        enrollment_ttl_s=300,
        cookie_name=_env("FRIDAY_SESSION_COOKIE", "friday_session"),
        require_physical_for_pair=_env("FRIDAY_REQUIRE_PHYSICAL_INPUT", phys_default).lower()
        not in ("0", "false", "no", "off"),
        passkeys_required=passkeys_required,
    )


def reset_auth_config() -> None:
    get_auth_config.cache_clear()
