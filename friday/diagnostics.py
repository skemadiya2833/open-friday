"""Startup configuration validation and health report.

``validate_config()`` reads the environment directly (so it is testable) and returns clear, actionable
issues. Errors stop the server from starting (``enforce``); warnings are only printed.
"""

from __future__ import annotations

import ipaddress
import os
import shutil
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class Issue:
    level: str          # "error" | "warn"
    key: str
    message: str

    def __str__(self) -> str:
        return f"[{self.level.upper()}] {self.key}: {self.message}"


_BOOLS = {"1", "0", "true", "false", "yes", "no", "on", "off", ""}
_INTS = {"FRIDAY_PORT": (1, 65535), "MAX_ITERATIONS": (1, 1000)}
_BOOL_KEYS = ("VOICE_ENABLED", "FRIDAY_SENSORS", "SKILL_PROPOSALS", "OVERLAY_ENABLED")
_CHOICES = {"CLOUD_PROVIDER": {"gemini", "openai", "none", ""}, "AGENT_BACKEND": {"legacy", "hybrid", ""},
            "VOICE_BARGE_IN": {"wake", "vad", "off", ""}}


def _is_loopback(host: str) -> bool:
    if host in ("localhost", ""):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def validate_config(env: dict[str, str] | None = None) -> list[Issue]:
    e = dict(os.environ if env is None else env)
    out: list[Issue] = []
    for key, (lo, hi) in _INTS.items():
        raw = e.get(key)
        if raw in (None, ""):
            continue
        try:
            v = int(raw)
        except ValueError:
            out.append(Issue("error", key, f"{raw!r} is not an integer. Use a number between {lo} and {hi}."))
            continue
        if not lo <= v <= hi:
            out.append(Issue("error", key, f"{v} is out of range ({lo}-{hi})."))
    for key in _BOOL_KEYS:
        if e.get(key, "").strip().lower() not in _BOOLS:
            out.append(Issue("error", key, f"{e[key]!r} is not a boolean. Use true or false."))
    for key, allowed in _CHOICES.items():
        v = e.get(key, "").strip().lower()
        if v not in allowed:
            out.append(Issue("error", key, f"{v!r} is not valid. Choose one of: {', '.join(sorted(a for a in allowed if a))}."))
    host = e.get("FRIDAY_HOST", "127.0.0.1")
    auth_mode = e.get("FRIDAY_AUTH", "local").strip().lower() or "local"
    public = e.get("FRIDAY_PUBLIC_HOST", "").strip()
    if auth_mode == "off":
        out.append(Issue("warn", "FRIDAY_AUTH",
                         "authentication is disabled (FRIDAY_AUTH=off). Safe only for local tests; "
                         "default is local (passkeys on loopback)."))
    if auth_mode == "remote" and not public:
        out.append(Issue("error", "FRIDAY_PUBLIC_HOST",
                         "FRIDAY_AUTH=remote requires a registrable hostname (not an IP). See docs/PHONE_SETUP.md."))
    if public and (public.replace(".", "").isdigit() or public.endswith(".local")):
        out.append(Issue("error", "FRIDAY_PUBLIC_HOST",
                         f"{public!r} is not a valid WebAuthn RP ID (Chromium rejects IPs and .local)."))
    if host in ("0.0.0.0", "::") and auth_mode != "remote":
        out.append(Issue("warn", "FRIDAY_HOST",
                         "all-interfaces bind ignored until FRIDAY_AUTH=remote and FRIDAY_PUBLIC_HOST are set; "
                         "server forces loopback. See docs/PHONE_SETUP.md."))
    # Non-loopback bind without remote auth → refuse to start (not just warn).
    if host and not _is_loopback(host) and host not in ("0.0.0.0", "::") and auth_mode != "remote":
        out.append(Issue("error", "FRIDAY_HOST",
                         f"non-loopback bind {host!r} requires FRIDAY_AUTH=remote and FRIDAY_PUBLIC_HOST. "
                         "Default is 127.0.0.1."))
    if e.get("FRIDAY_API_TOKEN", "").strip() and len(e["FRIDAY_API_TOKEN"].strip()) < 16:
        out.append(Issue("warn", "FRIDAY_API_TOKEN", "shorter than 16 characters; use a long random token."))
    shell = e.get("SHELL_TOOLS_ENABLED", "false").strip().lower()
    if shell in ("1", "true", "yes", "on"):
        out.append(Issue("warn", "SHELL_TOOLS_ENABLED",
                         "shell tools are enabled in the environment. Default is false; each call still needs "
                         "UI approval, but prefer leaving this off."))
    ollama = e.get("OLLAMA_HOST", "http://localhost:11434")
    if not ollama.startswith(("http://", "https://")):
        out.append(Issue("error", "OLLAMA_HOST", f"{ollama!r} must start with http:// or https://."))
    provider = e.get("CLOUD_PROVIDER", "gemini").strip().lower()
    key_name = {"gemini": "GEMINI_API_KEY", "openai": "OPENAI_API_KEY"}.get(provider)
    if key_name and e.get(key_name, "").strip() in ("", "your_gemini_api_key_here", "your_openai_key_if_using_openai"):
        out.append(Issue("warn", key_name, f"not set; the cloud fallback ({provider}) is disabled. Fine for local-only use."))
    if e.get("AGENT_BACKEND", "").strip().lower() == "hybrid" and not _mcp_windows_enabled():
        out.append(Issue("warn", "AGENT_BACKEND", "hybrid selected but the 'windows' server is not enabled in "
                         "config/mcp_servers.yaml; the agent cannot observe the desktop."))
    return out


def _mcp_windows_enabled() -> bool:
    try:
        import yaml

        p = Path(__file__).resolve().parent.parent / "config" / "mcp_servers.yaml"
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        servers = raw.get("servers", raw)
        w = servers.get("windows") if isinstance(servers, dict) else None
        return bool(w and w.get("enabled"))
    except Exception:  # noqa: BLE001
        return False


def enforce(issues: list[Issue] | None = None) -> list[Issue]:
    """Print issues; raise SystemExit with a readable message on any error."""
    issues = validate_config() if issues is None else issues
    for i in issues:
        print(f"[Friday] {i}")
    errors = [i for i in issues if i.level == "error"]
    if errors:
        raise SystemExit("Friday cannot start. Fix the configuration error(s) above (see .env.example).")
    return issues


def ollama_status(timeout: float = 1.5) -> dict[str, Any]:
    host = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    try:
        with urllib.request.urlopen(host + "/api/version", timeout=timeout) as r:  # noqa: S310 - owner-configured URL
            import json

            return {"up": True, "version": json.loads(r.read()).get("version")}
    except Exception as exc:  # noqa: BLE001
        return {"up": False, "error": type(exc).__name__}


def config_drift(env: dict[str, str] | None = None) -> dict[str, Any]:
    """Compare effective settings to safe defaults (shown on /health)."""
    e = dict(os.environ if env is None else env)
    safe = {
        "FRIDAY_HOST": "127.0.0.1",
        "FRIDAY_AUTH": "local",
        "SHELL_TOOLS_ENABLED": "false",
        "FRIDAY_PAIR_APPROVE": "physical",
    }
    effective = {
        "FRIDAY_HOST": e.get("FRIDAY_HOST", "127.0.0.1") or "127.0.0.1",
        "FRIDAY_AUTH": (e.get("FRIDAY_AUTH", "local") or "local").strip().lower(),
        "SHELL_TOOLS_ENABLED": (e.get("SHELL_TOOLS_ENABLED", "false") or "false").strip().lower(),
        "FRIDAY_PAIR_APPROVE": (e.get("FRIDAY_PAIR_APPROVE", "physical") or "physical").strip().lower(),
        "FRIDAY_PUBLIC_HOST": (e.get("FRIDAY_PUBLIC_HOST") or "").strip(),
    }
    drifted = {k: {"safe": safe[k], "effective": effective[k]}
               for k in safe if effective.get(k, "").lower() != safe[k].lower()}
    return {"safe_defaults": safe, "effective": effective, "drifted": drifted,
            "has_drift": bool(drifted)}


def health_report(*, probe_ollama: bool = True) -> dict[str, Any]:
    """Cheap, side-effect-free status. Never raises: each probe reports its own failure."""
    from friday.config import DATA_DIR

    rep: dict[str, Any] = {"ok": True}
    issues = validate_config()
    rep["config_issues"] = [str(i) for i in issues]
    rep["config_drift"] = config_drift()
    if any(i.level == "error" for i in issues):
        rep["ok"] = False
    rep["ollama"] = ollama_status() if probe_ollama else {"up": None}
    try:
        from friday.safety.audit import get_audit_log

        good, msg = get_audit_log().verify()
        rep["audit"] = {"chain_ok": good, "detail": msg}
        rep["ok"] = rep["ok"] and good
    except Exception as exc:  # noqa: BLE001
        rep["audit"] = {"chain_ok": None, "detail": f"{type(exc).__name__}: {exc}"}
    try:
        from friday.safety import physical

        m = physical.get_monitor()
        rep["physical_input_gate"] = {"required": physical.required(), "hook_running": m.running,
                                      "physical_events_seen": m.physical_count, "injected_events_seen": m.injected_count}
    except Exception as exc:  # noqa: BLE001
        rep["physical_input_gate"] = {"error": str(exc)}
    try:
        from friday.safety.estop import get_estop

        es = get_estop()
        rep["estop"] = {"registered": bool(es and es.registered), "hotkey": es.hotkey if es else None,
                        "error": es.error if es else "not started"}
    except Exception as exc:  # noqa: BLE001
        rep["estop"] = {"registered": False, "error": str(exc)}
    try:
        from friday.mcp_client import get_mcp_manager

        rep["mcp"] = get_mcp_manager().status()
    except Exception as exc:  # noqa: BLE001
        rep["mcp"] = {"error": str(exc)}
    try:
        from friday.agent.runs import get_run_manager

        rep["active_runs"] = [r.id for r in get_run_manager().active()]
    except Exception as exc:  # noqa: BLE001
        rep["active_runs"] = {"error": str(exc)}
    try:
        free = shutil.disk_usage(Path(DATA_DIR)).free / 2**30
        rep["data_dir_free_gb"] = round(free, 1)
        if free < 1:
            rep["ok"] = False
    except Exception:  # noqa: BLE001
        pass
    return rep


HEALTH_HTML = """<!doctype html><meta charset=utf-8><title>Friday health</title>
<style>body{font:14px system-ui;margin:2rem;max-width:60rem}pre{background:#111;color:#ddd;padding:1rem;overflow:auto}
.ok{color:#2a2}.bad{color:#c22}</style><h1>Friday health <span id=s></span></h1><pre id=o>loading...</pre>
<script>fetch('/api/health/detail').then(r=>r.json()).then(j=>{s.textContent=j.ok?'OK':'PROBLEM';s.className=j.ok?'ok':'bad';
o.textContent=JSON.stringify(j,null,2)}).catch(e=>{o.textContent=String(e)})</script>"""