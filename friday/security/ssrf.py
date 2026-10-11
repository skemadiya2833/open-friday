# Copyright 2025 The OpenJarvis Authors
# Licensed under the Apache License, Version 2.0
# Source: open-jarvis/OpenJarvis src/openjarvis/security/ssrf.py
# Commit: f9e9d5d28d9e58d7fe601c331fc15a02fad32b2c
# Changes for Friday: stdlib only; raises SSRFBlocked; no Rust.

"""SSRF protection — block requests to private IPs and cloud metadata endpoints."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

_BLOCKED_HOSTS = frozenset(
    {
        "169.254.169.254",
        "metadata.google.internal",
        "metadata.google.com",
        "100.100.100.200",
    }
)

_BLOCKED_CIDR = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("255.255.255.255/32"),
    ipaddress.ip_network("::/128"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("ff00::/8"),
]


class SSRFBlocked(ValueError):
    pass


def _is_blocked_ip(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    for net in _BLOCKED_CIDR:
        try:
            if addr in net:
                return True
        except TypeError:
            continue
    return False


def is_url_safe(url: str, *, resolve: bool = True) -> tuple[bool, str]:
    """Return (ok, reason). Default policy: block unsafe URLs."""
    try:
        parsed = urlparse(url)
    except Exception as exc:
        return False, f"bad url: {exc}"
    if parsed.scheme not in {"http", "https"}:
        return False, f"scheme not allowed: {parsed.scheme or '(none)'}"
    host = (parsed.hostname or "").lower().strip(".")
    if not host:
        return False, "missing host"
    if host in _BLOCKED_HOSTS:
        return False, f"blocked metadata host: {host}"
    # Literal IP in URL
    try:
        ip = ipaddress.ip_address(host)
        if _is_blocked_ip(ip):
            return False, f"blocked address: {host}"
    except ValueError:
        pass
    if not resolve:
        return True, "ok"
    try:
        infos = socket.getaddrinfo(host, parsed.port or 80, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        return False, f"dns failed: {exc}"
    for info in infos:
        sockaddr = info[4]
        try:
            ip = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            continue
        if _is_blocked_ip(ip):
            return False, f"resolves to blocked address: {ip}"
    return True, "ok"


def assert_url_safe(url: str, *, resolve: bool = True) -> None:
    ok, reason = is_url_safe(url, resolve=resolve)
    if not ok:
        raise SSRFBlocked(reason)
