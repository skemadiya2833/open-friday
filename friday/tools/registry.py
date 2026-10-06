"""Tool registry v2.

* thread-safe, runtime register / unregister (needed by the MCP client manager)
* JSON-Schema validated arguments, structured `ToolResult`
* every call goes through policy -> approval -> audit
* legacy helpers (`get_tool`, `list_tools`, `call_tool`, `tools_prompt_block`) keep working
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from friday.config import WORKSPACE_DIR, ensure_data_dirs
from friday.tools.paths import resolve_within
from friday.tools.types import ToolResult, ToolRisk, ToolSpec

__all__ = [
    "ToolRegistry", "ToolSpec", "ToolRisk", "ToolResult", "get_registry",
    "get_tool", "list_tools", "call_tool", "call_tool_result", "tools_prompt_block",
]


def _safe_workspace_path(rel: str) -> Path:
    """Resolve ``rel`` inside the workspace or raise ``ValueError`` (PathEscapeError)."""
    ensure_data_dirs()
    return resolve_within(WORKSPACE_DIR, rel)


def _shell_enabled() -> bool:
    import friday.config as cfg

    return bool(cfg.SHELL_TOOLS_ENABLED)


def _summarize(result: ToolResult) -> str:
    text = result.text().replace("\n", " ")
    return text[:300] + ("..." if len(text) > 300 else "")


class ToolRegistry:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._tools: dict[str, ToolSpec] = {}
        self._validators: dict[str, Draft202012Validator] = {}
        self.version = 0   # bumped on every change so UIs can poll cheaply

    # -- registration ------------------------------------------------------
    def register(self, spec: ToolSpec, *, replace: bool = False) -> None:
        Draft202012Validator.check_schema(spec.input_schema)
        with self._lock:
            if spec.name in self._tools and not replace:
                raise ValueError(f"tool already registered: {spec.name}")
            self._tools[spec.name] = spec
            self._validators[spec.name] = Draft202012Validator(spec.input_schema)
            self.version += 1

    def unregister(self, name: str) -> bool:
        with self._lock:
            existed = self._tools.pop(name, None) is not None
            self._validators.pop(name, None)
            if existed:
                self.version += 1
            return existed

    def unregister_source(self, source: str) -> int:
        with self._lock:
            names = [n for n, t in self._tools.items() if t.source == source]
            for n in names:
                self._tools.pop(n, None)
                self._validators.pop(n, None)
            if names:
                self.version += 1
            return len(names)

    # -- lookup ------------------------------------------------------------
    def get(self, name: str) -> ToolSpec | None:
        with self._lock:
            return self._tools.get(name)

    def list(self, allowed: list[str] | None = None) -> list[ToolSpec]:
        with self._lock:
            if allowed is None:
                return list(self._tools.values())
            return [self._tools[n] for n in allowed if n in self._tools]

    # -- execution ---------------------------------------------------------
    def call(
        self,
        name: str,
        args: dict[str, Any] | None,
        *,
        caller: str = "agent",
        run_id: str | None = None,
    ) -> ToolResult:
        from friday.safety.approval import get_approval_service
        from friday.safety.audit import get_audit_log
        from friday.safety.policy import get_policy

        args = dict(args or {})
        audit = get_audit_log()
        with self._lock:
            spec = self._tools.get(name)
            validator = self._validators.get(name)

        if spec is None or validator is None:
            audit.record(tool=name, args=args, outcome="unknown_tool", approver="n/a",
                         risk="unknown", caller=caller, run_id=run_id)
            return ToolResult.error(f"Unknown tool: {name}")

        errors = sorted(validator.iter_errors(args), key=lambda e: list(e.path))
        if errors:
            msg = "; ".join(
                f"{'.'.join(str(p) for p in e.path) or '(args)'}: {e.message}" for e in errors[:5]
            )
            audit.record(tool=name, args=args, outcome="invalid", approver="n/a",
                         risk=spec.risk.value, caller=caller, run_id=run_id, detail=msg)
            return ToolResult.error(f"Invalid arguments for {name}: {msg}")

        policy = get_policy()
        decision = policy.decide(name, spec.risk, shell_enabled=_shell_enabled())
        approver = f"policy:{decision.action}"

        if decision.action == "ask" and name == "run_shell" and policy.shell.is_allowlisted(str(args.get("command", ""))):
            decision.action, approver = "allow", "policy:allowlist"

        if decision.action == "deny":
            audit.record(tool=name, args=args, outcome="denied", approver="policy:deny",
                         risk=spec.risk.value, caller=caller, run_id=run_id, detail=decision.reason)
            return ToolResult.error(f"Denied by policy: {decision.reason}", denied=True)

        if decision.action == "ask":
            approved, who = get_approval_service().request(
                tool=name, risk=spec.risk.value, args=args, reason=decision.reason,
                caller=caller, run_id=run_id,
            )
            approver = who
            if not approved:
                audit.record(tool=name, args=args, outcome="denied", approver=who,
                             risk=spec.risk.value, caller=caller, run_id=run_id, detail="owner approval not granted")
                return ToolResult.error(f"Not approved ({who}). The owner did not allow {name}.", denied=True)

        t0 = time.perf_counter()
        try:
            raw = spec.handler(args)
            result = raw if isinstance(raw, ToolResult) else ToolResult.text_result(str(raw))
            outcome = "error" if result.is_error else "ok"
        except Exception as exc:  # noqa: BLE001 - tools must not crash the caller
            result = ToolResult.error(f"Tool error ({name}): {exc}")
            outcome = "error"
        dur = (time.perf_counter() - t0) * 1000.0
        audit.record(tool=name, args=args, outcome=outcome, approver=approver, risk=spec.risk.value,
                     duration_ms=dur, result_summary=_summarize(result), caller=caller, run_id=run_id)
        return result


_registry: ToolRegistry | None = None
_registry_lock = threading.Lock()


def get_registry() -> ToolRegistry:
    global _registry
    with _registry_lock:
        if _registry is None:
            from friday.tools.builtin import builtin_specs

            reg = ToolRegistry()
            for spec in builtin_specs():
                reg.register(spec)
            _registry = reg
        return _registry


def reset_registry() -> None:
    """Test hook."""
    global _registry
    with _registry_lock:
        _registry = None


# ---------------------------------------------------------------------------
# Legacy (v1) function API
# ---------------------------------------------------------------------------

def get_tool(name: str) -> ToolSpec | None:
    return get_registry().get(name)


def list_tools(allowed: list[str] | None = None) -> list[ToolSpec]:
    return get_registry().list(allowed)


def call_tool_result(name: str, args: dict[str, Any] | None, *, caller: str = "agent",
                     run_id: str | None = None) -> ToolResult:
    return get_registry().call(name, args, caller=caller, run_id=run_id)


def call_tool(name: str, args: dict[str, Any] | None, *, caller: str = "agent",
              run_id: str | None = None) -> str:
    """v1-compatible: returns text only. Prefer :func:`call_tool_result`."""
    return call_tool_result(name, args, caller=caller, run_id=run_id).text()


def tools_prompt_block(allowed: list[str]) -> str:
    lines = []
    for t in list_tools(allowed):
        props = t.input_schema.get("properties", {})
        required = set(t.input_schema.get("required", []))
        sig = ", ".join(
            f"{k}{'' if k in required else '?'}:{v.get('type', 'any')}" for k, v in props.items()
        )
        lines.append(f"- {t.name}({sig}): {t.description}")
    return "\n".join(lines)


def tool_schema_json(name: str) -> str:
    spec = get_tool(name)
    return json.dumps(spec.input_schema) if spec else "{}"
