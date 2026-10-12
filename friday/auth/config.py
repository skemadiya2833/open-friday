"""Auth / WebAuthn configuration.

Modes:
  off    — no auth (tests)
  local  — this PC only (loopback); no passkey login wall
  remote — phone / LAN via public hostname; passkeys required

Remote stays OFF until FRIDAY_PUBLIC_HOST (registrable domain) is set.
RP ID must be that hostname — never an IP and never .local (Chromium rejects both).
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
    mode: str                       # off | local | remote
    rp_id: str                      # localhost | friday.example.com
    rp_name: str
    origin: str                     # primary origin (cookie / docs)
    origins: tuple[str, ...]        # all accepted WebAuthn origins
    public_host: str                # empty until owner configures DNS+cert
    bind_loopback_only: bool
    session_ttl_s: int
    stepup_ttl_s: int
    enrollment_ttl_s: int
    cookie_name: str
    require_physical_for_pair: bool


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
    if mode not in ("off", "local", "remote"):
        mode = "local"
    public = _env("FRIDAY_PUBLIC_HOST")
    # Local PC uses http on FRIDAY_PORT; remote mode sets HTTPS origin via FRIDAY_ORIGIN / public host.
    http_port = int(_env("FRIDAY_PORT", "8787") or "8787")

    if mode == "remote" and public and _valid_rp_id(public):
        rp_id = public.lower()
        origin = (_env("FRIDAY_ORIGIN") or f"https://{rp_id}").rstrip("/")
        origins = (origin,)
        bind_loopback = False
    elif mode == "off":
        rp_id = "localhost"
        origin = f"http://127.0.0.1:{http_port}"
        origins = (origin, f"http://localhost:{http_port}")
        bind_loopback = True
    else:
        # local: this PC, loopback bind, no login wall. Passkey ceremony still
        # available to pre-register devices before switching to remote.
        mode = "local"
        rp_id = "localhost"
        origin = (_env("FRIDAY_ORIGIN") or f"http://localhost:{http_port}").rstrip("/")
        origins = tuple(dict.fromkeys([
            origin,
            f"http://localhost:{http_port}",
            f"http://127.0.0.1:{http_port}",
        ]))
        bind_loopback = True
        public = ""

    return AuthConfig(
        mode=mode,
        rp_id=rp_id,
        rp_name=_env("FRIDAY_RP_NAME", "Friday"),
        origin=origin,
        origins=origins,
        public_host=public.lower(),
        bind_loopback_only=bind_loopback,
        session_ttl_s=int(_env("FRIDAY_SESSION_TTL", "86400") or "86400"),
        stepup_ttl_s=60,
        enrollment_ttl_s=300,
        cookie_name=_env("FRIDAY_SESSION_COOKIE", "friday_session"),
        require_physical_for_pair=_env("FRIDAY_REQUIRE_PHYSICAL_INPUT", "true").lower()
        not in ("0", "false", "no", "off"),
    )


def reset_auth_config() -> None:
    get_auth_config.cache_clear()
