from __future__ import annotations

from enum import Enum


class Role(str, Enum):
    CHAT = "chat"                     # chat + reminders only (new device default)
    TOOLS = "tools"                   # + memory/files/tools that are not desktop
    DESKTOP = "desktop-control"       # + computer_use / approvals for desktop
    ADMIN = "admin"                   # pair devices, roles, export, shell enable


_ORDER = [Role.CHAT, Role.TOOLS, Role.DESKTOP, Role.ADMIN]


def role_at_least(have: str | Role, need: str | Role) -> bool:
    try:
        h = Role(have) if not isinstance(have, Role) else have
        n = Role(need) if not isinstance(need, Role) else need
    except ValueError:
        return False
    return _ORDER.index(h) >= _ORDER.index(n)


def parse_role(value: str, default: Role = Role.CHAT) -> Role:
    try:
        return Role(value)
    except ValueError:
        return default
