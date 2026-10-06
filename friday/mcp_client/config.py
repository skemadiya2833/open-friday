"""MCP server configuration (YAML), validated strictly."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from friday.tools.types import ToolRisk

_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,31}$")

DEFAULT_INHERIT_ENV = [
    "PATH", "PATHEXT", "SystemRoot", "SystemDrive", "ComSpec", "USERPROFILE", "HOMEDRIVE", "HOMEPATH",
    "LOCALAPPDATA", "APPDATA", "ProgramData", "ProgramFiles", "ProgramFiles(x86)", "TEMP", "TMP",
    "USERNAME", "COMPUTERNAME",
]


class McpConfigError(ValueError):
    pass


@dataclass
class ServerConfig:
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None
    enabled: bool = False
    description: str = ""
    startup_timeout: float = 120.0
    call_timeout: float = 60.0
    exclude_tools: list[str] = field(default_factory=list)
    trust_annotations: bool = False
    risk_default: ToolRisk = ToolRisk.CONFIRM
    risk_safe: set[str] = field(default_factory=set)
    risk_confirm: set[str] = field(default_factory=set)
    risk_dangerous: set[str] = field(default_factory=set)

    def risk_for(self, tool: str, annotations: dict[str, Any] | None) -> ToolRisk:
        """Explicit config wins; annotations only matter if `trust_annotations` is set."""
        if tool in self.risk_dangerous:
            return ToolRisk.DANGEROUS
        if tool in self.risk_safe:
            return ToolRisk.SAFE
        if tool in self.risk_confirm:
            return ToolRisk.CONFIRM
        if self.trust_annotations and annotations:
            if annotations.get("read_only_hint") is True:
                return ToolRisk.SAFE
            if annotations.get("destructive_hint") is True:
                return ToolRisk.CONFIRM
        return self.risk_default


@dataclass
class McpConfig:
    inherit_env: list[str]
    servers: dict[str, ServerConfig]


def _as_str_list(v: Any, where: str) -> list[str]:
    if v is None:
        return []
    if not isinstance(v, list):
        raise McpConfigError(f"{where} must be a list")
    return [str(x) for x in v]


def parse_config(raw: dict[str, Any]) -> McpConfig:
    if not isinstance(raw, dict):
        raise McpConfigError("config must be a mapping")
    if raw.get("version", 1) != 1:
        raise McpConfigError(f"unsupported config version {raw.get('version')}")
    inherit = _as_str_list(raw.get("inherit_env"), "inherit_env") or list(DEFAULT_INHERIT_ENV)
    servers: dict[str, ServerConfig] = {}
    for name, s in (raw.get("servers") or {}).items():
        if not _NAME_RE.match(str(name)):
            raise McpConfigError(f"invalid server name '{name}' (letters, digits, _ and - only)")
        if not isinstance(s, dict) or not s.get("command"):
            raise McpConfigError(f"servers.{name}.command is required")
        risk = s.get("risk") or {}
        default = str(risk.get("default", "confirm")).lower()
        if default not in {r.value for r in ToolRisk}:
            raise McpConfigError(f"servers.{name}.risk.default invalid: {default}")
        env = {str(k): "" if v is None else str(v) for k, v in (s.get("env") or {}).items()}
        servers[str(name)] = ServerConfig(
            name=str(name),
            command=str(s["command"]),
            args=_as_str_list(s.get("args"), f"servers.{name}.args"),
            env=env,
            cwd=s.get("cwd"),
            enabled=bool(s.get("enabled", False)),
            description=str(s.get("description", "")).strip(),
            startup_timeout=float(s.get("startup_timeout_seconds", 120)),
            call_timeout=float(s.get("call_timeout_seconds", 60)),
            exclude_tools=_as_str_list(s.get("exclude_tools"), f"servers.{name}.exclude_tools"),
            trust_annotations=bool(s.get("trust_annotations", False)),
            risk_default=ToolRisk(default),
            risk_safe=set(_as_str_list(risk.get("safe"), "risk.safe")),
            risk_confirm=set(_as_str_list(risk.get("confirm"), "risk.confirm")),
            risk_dangerous=set(_as_str_list(risk.get("dangerous"), "risk.dangerous")),
        )
        clash = servers[str(name)].risk_safe & servers[str(name)].risk_dangerous
        if clash:
            raise McpConfigError(f"servers.{name}: tools both safe and dangerous: {sorted(clash)}")
    return McpConfig(inherit_env=inherit, servers=servers)


def load_config(path: str | Path | None = None) -> McpConfig:
    from friday.config import MCP_CONFIG_PATH

    p = Path(path or MCP_CONFIG_PATH)
    if not p.exists():
        return McpConfig(inherit_env=list(DEFAULT_INHERIT_ENV), servers={})
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise McpConfigError(f"{p}: invalid YAML: {exc}") from exc
    try:
        return parse_config(raw)
    except McpConfigError as exc:
        raise McpConfigError(f"{p}: {exc}") from exc
