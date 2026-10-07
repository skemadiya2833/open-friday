"""LAN phone access: Windows Firewall often drops inbound 8787 even when the server is bound."""

from __future__ import annotations

import subprocess
import sys

RULE_NAME = "Friday Control Center 8787"
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _netsh(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["netsh", "advfirewall", "firewall", *args],
        capture_output=True,
        text=True,
        timeout=12,
        creationflags=_CREATE_NO_WINDOW,
    )


def add_rule_args(port: int) -> list[str]:
    return [
        "add",
        "rule",
        f"name={RULE_NAME}",
        "dir=in",
        "action=allow",
        "protocol=TCP",
        f"localport={int(port)}",
        "profile=private",
        "enable=yes",
    ]


def inbound_rule_present(port: int) -> bool:
    if sys.platform != "win32":
        return True
    try:
        r = _netsh("show", "rule", f"name={RULE_NAME}")
    except Exception:  # noqa: BLE001
        return False
    out = (r.stdout or "") + (r.stderr or "")
    return r.returncode == 0 and "Enabled" in out and str(port) in out


def ensure_inbound(port: int) -> str:
    """Try to allow TCP `port` on the Private profile. Never raises. Returns a short status."""
    if sys.platform != "win32":
        return "ok"
    if inbound_rule_present(port):
        return "ok"
    try:
        r = _netsh(*add_rule_args(port))
    except Exception as exc:  # noqa: BLE001
        return f"error:{exc}"
    out = ((r.stdout or "") + (r.stderr or "")).strip()
    if r.returncode == 0:
        return "added"
    low = out.lower()
    if "access is denied" in low or "requested operation requires elevation" in low:
        cmd = "netsh advfirewall firewall " + " ".join(add_rule_args(port))
        print(
            f"[Friday] Phone cannot connect: Windows Firewall is blocking TCP {port}.\n"
            f"         Allow it once (Admin PowerShell):\n"
            f"         {cmd}",
            flush=True,
        )
        return "need_admin"
    print(f"[Friday] WARNING: could not add firewall rule: {out[:200]}", flush=True)
    return "failed"
