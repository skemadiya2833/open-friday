"""Owner runtime prefs — Systems UI overrides .env for everyday knobs.

Resolution order for each key:
  1. Value in ``data/runtime_prefs.json`` (set from Systems)
  2. Environment variable (if set)
  3. Optimum default from SCHEMA

Host/bind/auth/API keys/paths stay env-only (need restart / security).
"""

from __future__ import annotations

import json
import os
import threading
from copy import deepcopy
from typing import Any, Literal

from friday.atomic import write_text_atomic

PrefKind = Literal["bool", "str", "choice", "int", "float"]

# Optimum defaults: sensible first-run values. UI "Reset to optima" restores these.
SCHEMA: dict[str, dict[str, Any]] = {
    "owner_name": {
        "kind": "str",
        "default": "boss",
        "env": "FRIDAY_OWNER_NAME",
        "group": "persona",
        "label": "Preferred address",
        "help": "How Friday addresses you aloud (default: boss). Say \"call me …\" anytime, or change here. Real names stay in Memory unless you ask to be called that.",
    },
    "humor": {
        "kind": "choice",
        "choices": ["off", "dry", "full", "roast"],
        "default": "dry",
        "env": "FRIDAY_HUMOR",
        "group": "persona",
        "label": "Humor",
        "help": "Dry is the sweet spot. Roast is opt-in only.",
    },
    "deep": {
        "kind": "bool",
        "default": False,
        "env": "FRIDAY_DEEP",
        "group": "persona",
        "label": "Deep think",
        "help": "Bounded extra reasoning for hard asks (slower).",
    },
    "toasts": {
        "kind": "bool",
        "default": True,
        "env": "FRIDAY_TOASTS",
        "group": "persona",
        "label": "Windows toasts",
        "help": "Desktop notifications for approvals and alerts.",
    },
    "agent_backend": {
        "kind": "choice",
        "choices": ["auto", "legacy", "hybrid"],
        "default": "auto",
        "env": "AGENT_BACKEND",
        "group": "agent",
        "label": "Desktop agent",
        "help": "Auto = hybrid when Windows-MCP is on, else legacy vision loop.",
    },
    "tools_first": {
        "kind": "bool",
        "default": True,
        "env": "FRIDAY_TOOLS_FIRST",
        "group": "agent",
        "label": "Tools before GUI",
        "help": "Prefer deterministic tools before clicking the desktop.",
    },
    "memory": {
        "kind": "choice",
        "choices": ["off", "record", "read", "on"],
        "default": "off",
        "env": "FRIDAY_MEMORY",
        "group": "agent",
        "label": "Experience memory",
        "help": "Off by default. On = record + read run notes (not chat history).",
    },
    "approval_mode": {
        "kind": "choice",
        "choices": ["attended", "unattended"],
        "default": "attended",
        "env": "FRIDAY_APPROVAL_MODE",
        "group": "safety",
        "label": "Approval mode",
        "help": "Attended waits for you. Unattended auto-allows policy-permitted tools.",
    },
    "approval_beep": {
        "kind": "bool",
        "default": True,
        "env": "FRIDAY_APPROVAL_BEEP",
        "group": "safety",
        "label": "Approval beep",
        "help": "Audible nudge when Friday needs a confirm.",
    },
    "blackout": {
        "kind": "bool",
        "default": False,
        "env": "FRIDAY_BLACKOUT",
        "group": "safety",
        "label": "Blackout (local only)",
        "help": "Block web research and outbound network tools; stay on local models.",
    },
    "diary": {
        "kind": "bool",
        "default": True,
        "env": "FRIDAY_DIARY",
        "group": "persona",
        "label": "Daily diary",
        "help": "Log notable work to a local day file for continuity and briefings.",
    },
    "shell_tools": {
        "kind": "bool",
        "default": False,
        "env": "SHELL_TOOLS_ENABLED",
        "group": "safety",
        "label": "Shell tools",
        "help": "Allow PowerShell tool (still needs per-call approval). Keep off unless you need it.",
    },
    "sensors": {
        "kind": "bool",
        "default": False,
        "env": "FRIDAY_SENSORS",
        "group": "safety",
        "label": "Sensor tool",
        "help": "Read-only hardware/sensor probe tool.",
    },
    "tts_engine": {
        "kind": "choice",
        "choices": ["auto", "kokoro", "piper", "edge", "gtts", "local"],
        "default": "auto",
        "env": "FRIDAY_TTS_ENGINE",
        "group": "voice",
        "label": "TTS engine",
        "help": "Auto prefers local Kokoro (natural female). Edge often fails (403). Piper is a lighter local neural fallback.",
    },
    "tts_voice": {
        "kind": "choice",
        "choices": [
            "af_heart",
            "af_bella",
            "af_nicole",
            "af_sarah",
            "bf_emma",
            "en-US-AvaNeural",
            "en-US-JennyNeural",
            "en-US-AriaNeural",
            "en-GB-SoniaNeural",
        ],
        "default": "af_heart",
        "env": "VOICE_TTS_VOICE",
        "group": "voice",
        "label": "TTS voice",
        "help": "Kokoro female voices (af_*) preferred. Edge Neural names only used when engine is Edge.",
    },
    "complexity_routing": {
        "kind": "bool",
        "default": False,
        "env": "FRIDAY_COMPLEXITY_ROUTING",
        "group": "models",
        "label": "Complexity routing",
        "help": "Heuristic fast/main model routing (needs role models installed).",
    },
    "model_roles": {
        "kind": "bool",
        "default": False,
        "env": "FRIDAY_MODEL_ROLES",
        "group": "models",
        "label": "Model role map",
        "help": "Use separate fast/main/vision/coder models when installed.",
    },
    "low_end": {
        "kind": "bool",
        "default": False,
        "env": "LOW_END_MODE",
        "group": "perf",
        "label": "Low-end mode",
        "help": "Lighter frames and verify — for weaker GPUs. Restart recommended.",
        "restart": True,
    },
}

_GROUPS = [
    ("persona", "Persona"),
    ("agent", "Agent"),
    ("safety", "Safety"),
    ("voice", "Voice"),
    ("models", "Models"),
    ("perf", "Performance"),
]

_lock = threading.RLock()
_cache: dict[str, Any] | None = None


def _path():
    from friday.config import DATA_DIR
    from pathlib import Path

    return Path(DATA_DIR) / "runtime_prefs.json"


def clear_cache() -> None:
    global _cache
    with _lock:
        _cache = None


def load_raw() -> dict[str, Any]:
    global _cache
    with _lock:
        if _cache is not None:
            return dict(_cache)
        path = _path()
        if not path.is_file():
            _cache = {}
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            _cache = raw if isinstance(raw, dict) else {}
        except Exception:  # noqa: BLE001
            _cache = {}
        return dict(_cache)


def save_raw(data: dict[str, Any]) -> dict[str, Any]:
    global _cache
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        clean = {k: v for k, v in data.items() if k in SCHEMA}
        write_text_atomic(path, json.dumps(clean, indent=2) + "\n")
        _cache = dict(clean)
        return dict(clean)


def _coerce(spec: dict[str, Any], raw: Any) -> Any:
    kind = spec["kind"]
    if kind == "bool":
        if isinstance(raw, bool):
            return raw
        return str(raw).strip().lower() in ("1", "true", "yes", "on")
    if kind == "int":
        return int(raw)
    if kind == "float":
        return float(raw)
    if kind == "choice":
        choices = list(spec.get("choices") or [])
        lower_map = {str(c).lower(): c for c in choices}
        key = str(raw).strip().lower()
        if key in lower_map:
            return lower_map[key]
        return deepcopy(spec["default"])
    s = str(raw).strip()
    return s or deepcopy(spec["default"])


def _from_env(spec: dict[str, Any]) -> Any | None:
    env = spec.get("env")
    if not env or env not in os.environ:
        return None
    raw = os.environ.get(env)
    if raw is None:
        return None
    # Empty AGENT_BACKEND means auto — treat as unset so default applies
    if env == "AGENT_BACKEND" and not str(raw).strip():
        return None
    return _coerce(spec, raw)


def get(key: str) -> Any:
    """Effective value: prefs → env → optimum default."""
    spec = SCHEMA.get(key)
    if not spec:
        raise KeyError(key)
    raw = load_raw()
    if key in raw and raw[key] is not None:
        return _coerce(spec, raw[key])
    env_val = _from_env(spec)
    if env_val is not None:
        return env_val
    return deepcopy(spec["default"])


def source_of(key: str) -> str:
    spec = SCHEMA[key]
    raw = load_raw()
    if key in raw and raw[key] is not None:
        return "ui"
    if _from_env(spec) is not None:
        return "env"
    return "default"


def update(patch: dict[str, Any]) -> dict[str, Any]:
    """Merge UI patch into prefs. Unknown keys ignored. None deletes key (fall back to env/default)."""
    data = load_raw()
    for key, val in patch.items():
        if key not in SCHEMA:
            continue
        if val is None:
            data.pop(key, None)
            continue
        data[key] = _coerce(SCHEMA[key], val)
    return save_raw(data)


def reset_to_optima() -> dict[str, Any]:
    """Write all optimum defaults into prefs so UI owns every knobs."""
    optima = {k: deepcopy(s["default"]) for k, s in SCHEMA.items()}
    return save_raw(optima)


def clear_all() -> dict[str, Any]:
    """Remove UI overrides (env + code defaults apply again)."""
    return save_raw({})


def snapshot() -> dict[str, Any]:
    """Full Systems payload: groups, effective values, sources, schema."""
    items = []
    for key, spec in SCHEMA.items():
        items.append(
            {
                "key": key,
                "value": get(key),
                "default": deepcopy(spec["default"]),
                "source": source_of(key),
                "kind": spec["kind"],
                "choices": list(spec.get("choices") or []),
                "group": spec["group"],
                "label": spec["label"],
                "help": spec.get("help") or "",
                "restart": bool(spec.get("restart")),
                "env": spec.get("env") or "",
            }
        )
    return {
        "groups": [{"id": gid, "label": label} for gid, label in _GROUPS],
        "items": items,
        "path": str(_path()),
    }
