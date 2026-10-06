"""Tool policy: maps (tool, risk tier) to allow / ask / deny. Fails closed."""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from friday.tools.types import ToolRisk

VALID_DECISIONS = {"allow", "ask", "deny"}
_DEFAULT_TIERS = {"safe": "allow", "confirm": "ask", "dangerous": "deny"}


class PolicyError(ValueError):
    pass


@dataclass
class ShellPolicy:
    mode: str = "ask"
    timeout_seconds: float = 30.0
    max_timeout_seconds: float = 120.0
    max_output_chars: int = 4000
    allowlist: list[re.Pattern[str]] = field(default_factory=list)

    def is_allowlisted(self, command: str) -> bool:
        return self.mode == "allowlist" and any(p.fullmatch(command.strip()) for p in self.allowlist)


@dataclass
class Decision:
    action: str      # allow | ask | deny
    reason: str


@dataclass
class Policy:
    tiers: dict[str, str] = field(default_factory=lambda: dict(_DEFAULT_TIERS))
    tools: dict[str, str] = field(default_factory=dict)
    shell: ShellPolicy = field(default_factory=ShellPolicy)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Policy":
        if not isinstance(raw, dict):
            raise PolicyError("policy must be a mapping")
        if raw.get("version", 1) != 1:
            raise PolicyError(f"unsupported policy version: {raw.get('version')}")

        tiers = dict(_DEFAULT_TIERS)
        for k, v in (raw.get("tiers") or {}).items():
            if k not in _DEFAULT_TIERS:
                raise PolicyError(f"unknown tier '{k}' (expected safe|confirm|dangerous)")
            tiers[k] = _decision(v, f"tiers.{k}")

        tools = {str(k): _decision(v, f"tools.{k}") for k, v in (raw.get("tools") or {}).items()}

        sh = raw.get("shell") or {}
        mode = str(sh.get("mode", "ask"))
        if mode not in ("ask", "allowlist"):
            raise PolicyError("shell.mode must be 'ask' or 'allowlist'")
        try:
            allow = [re.compile(p) for p in (sh.get("allowlist") or [])]
        except re.error as exc:
            raise PolicyError(f"invalid shell.allowlist regex: {exc}") from exc
        shell = ShellPolicy(
            mode=mode,
            timeout_seconds=float(sh.get("timeout_seconds", 30)),
            max_timeout_seconds=float(sh.get("max_timeout_seconds", 120)),
            max_output_chars=int(sh.get("max_output_chars", 4000)),
            allowlist=allow,
        )
        if shell.timeout_seconds <= 0 or shell.timeout_seconds > shell.max_timeout_seconds:
            raise PolicyError("shell.timeout_seconds must be in (0, max_timeout_seconds]")
        return cls(tiers=tiers, tools=tools, shell=shell)

    def decide(self, tool: str, risk: ToolRisk, *, shell_enabled: bool = False) -> Decision:
        tools = dict(self.tools)
        # Shell is double-gated: the env switch must be on *and* policy must not deny it.
        if tool == "run_shell":
            if not shell_enabled:
                return Decision("deny", "shell tools are disabled (set SHELL_TOOLS_ENABLED=true to allow)")
            tools.setdefault("run_shell", "ask")
            if tools["run_shell"] == "allow":
                # Never allow blanket unattended shell from a YAML typo.
                tools["run_shell"] = "ask"
        if tool in tools:
            return Decision(tools[tool], f"tool override '{tool}' -> {tools[tool]}")
        action = self.tiers.get(risk.value, "deny")
        return Decision(action, f"tier '{risk.value}' -> {action}")


def _decision(value: Any, where: str) -> str:
    v = str(value).strip().lower()
    if v not in VALID_DECISIONS:
        raise PolicyError(f"{where}: '{value}' is not one of allow|ask|deny")
    return v


def load_policy(path: str | Path | None = None) -> Policy:
    from friday.config import POLICY_PATH

    p = Path(path or POLICY_PATH)
    if not p.exists():
        return Policy()  # built-in conservative defaults
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise PolicyError(f"{p}: invalid YAML: {exc}") from exc
    try:
        return Policy.from_dict(raw)
    except PolicyError as exc:
        raise PolicyError(f"{p}: {exc}") from exc


_policy: Policy | None = None
_policy_lock = threading.Lock()


def get_policy() -> Policy:
    global _policy
    with _policy_lock:
        if _policy is None:
            _policy = load_policy()
        return _policy


def set_policy(policy: Policy | None) -> None:
    global _policy
    with _policy_lock:
        _policy = policy
