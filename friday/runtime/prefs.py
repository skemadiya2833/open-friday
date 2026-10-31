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

PrefKind = Literal["bool", "str", "secret", "choice", "int", "float"]

# Mask shown to Systems GET when a secret is stored (never return plaintext).
SECRET_MASK = "••••••••"
# Client may send this sentinel on PATCH to mean "keep existing secret".
SECRET_KEEP = "__KEEP__"

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
        "help": "Attended (default) shows Allow/Deny for shell & risky tools. Unattended denies anything that needs a click — only for benches. Interactive use should stay Attended.",
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
        "default": True,
        "env": "SHELL_TOOLS_ENABLED",
        "group": "safety",
        "label": "Shell tools",
        "help": "Allow PowerShell for terminal-first work (still needs per-call approval). Turn off to force GUI-only.",
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
    "chat_model": {
        "kind": "str",
        "default": "gemma4:12b",
        "env": "CHAT_MODEL",
        "group": "models",
        "label": "Chat model",
        "help": "Ollama tag for talk / tools / research. On 16 GB prefer one multimodal for chat+vision (e.g. gemma4:12b, or saluki only if built with mmproj).",
    },
    "vision_model": {
        "kind": "str",
        "default": "gemma4:12b",
        "env": "VISION_MODEL",
        "group": "models",
        "label": "Vision model",
        "help": "Ollama tag for screen / camera look. Use a multimodal tag (gemma4, qwen3-vl, …).",
    },
    "complexity_routing": {
        "kind": "bool",
        "default": False,
        "env": "FRIDAY_COMPLEXITY_ROUTING",
        "group": "models",
        "label": "Complexity routing",
        "help": "Off by default — stays on one model. On = heuristic fast/main split (can load a second model).",
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
    # --- CAD / FreeCAD + Taiga-S1 (Systems UI + Friday can change these) ---
    "cad_enabled": {
        "kind": "bool",
        "default": False,
        "env": "FRIDAY_CAD",
        "group": "cad",
        "label": "CAD builds",
        "help": "Allow FreeCAD + Taiga-S1 part builds. Friday can toggle this when you ask.",
    },
    "freecad_install": {
        "kind": "str",
        "default": r"C:\Program Files\FreeCAD 1.1",
        "env": "FREECAD_INSTALL",
        "group": "cad",
        "label": "FreeCAD install folder",
        "help": "Root folder that contains bin\\freecad.exe (auto-detected when empty/wrong).",
    },
    "freecad_s1_repo": {
        "kind": "str",
        "default": "",
        "env": "FREECAD_S1_REPO",
        "group": "cad",
        "label": "biome-s1 / Taiga repo",
        "help": "Checkout of github.com/shhivv/biome-s1. Empty = data/vendor/biome-s1 after Setup.",
    },
    "freecad_s1_python": {
        "kind": "str",
        "default": "",
        "env": "FREECAD_S1_PYTHON",
        "group": "cad",
        "label": "Taiga worker Python",
        "help": "Python 3.11/3.12 with torch + freecad_s1 (usually biome-s1\\.venv\\Scripts\\python.exe).",
    },
    "freecad_s1_model": {
        "kind": "str",
        "default": "shhivv/taiga-s1",
        "env": "FREECAD_S1_MODEL",
        "group": "cad",
        "label": "Taiga model",
        "help": "Hugging Face id or local weights folder.",
    },
    "freecad_s1_port": {
        "kind": "int",
        "default": 8765,
        "env": "FREECAD_S1_PORT",
        "group": "cad",
        "label": "Taiga socket port",
        "help": "Local FreeCAD GUI server port (default 8765).",
    },
    # --- Channels / integrations (phone Control Center + optional Telegram) ---
    "telegram_enabled": {
        "kind": "bool",
        "default": False,
        "env": "FRIDAY_TELEGRAM",
        "group": "channels",
        "label": "Telegram remote",
        "help": "Optional phone channel via Bot API (ZYRON-style). Passkey Control Center still works. Off by default.",
    },
    "telegram_bot_token": {
        "kind": "secret",
        "default": "",
        "env": "FRIDAY_TELEGRAM_BOT_TOKEN",
        "group": "channels",
        "label": "Telegram bot token",
        "help": "From @BotFather. Stored locally; Systems never shows the plaintext after save. Leave blank to clear.",
        "secret": True,
    },
    "telegram_allowed_chat_ids": {
        "kind": "str",
        "default": "",
        "env": "FRIDAY_TELEGRAM_CHAT_IDS",
        "group": "channels",
        "label": "Telegram allowed chat IDs",
        "help": "Comma-separated chat IDs that may talk to Friday. Empty = deny all (safe).",
    },
    "cua_enabled": {
        "kind": "bool",
        "default": False,
        "env": "FRIDAY_CUA",
        "group": "channels",
        "label": "Cua Driver (MCP)",
        "help": "Start trycua Cua Driver as an MCP server when installed (background computer-use). Off by default.",
    },
    "artemis_enabled": {
        "kind": "bool",
        "default": False,
        "env": "FRIDAY_ARTEMIS",
        "group": "channels",
        "label": "Artemis phone agent (MCP)",
        "help": (
            "Google Artemis — drive a USB/emulator Android phone from chat via MCP. "
            "Clones to data/vendor/artemis on enable. Needs ADB + device and GOOGLE_API_KEY "
            "(or GEMINI_API_KEY) in the environment. Off by default."
        ),
    },
    "skill_hub_fetch": {
        "kind": "bool",
        "default": False,
        "env": "FRIDAY_SKILL_HUB_FETCH",
        "group": "channels",
        "label": "Skill hub fetch",
        "help": "Allow importing SKILL.md from git/HTTPS into the inbox (quarantine → owner approve). Off by default.",
    },
    "presence_orb": {
        "kind": "bool",
        "default": True,
        "env": "FRIDAY_PRESENCE_ORB",
        "group": "persona",
        "label": "Presence working bubble",
        "help": "Show a request-scoped working bubble on the HUD orb during long tool runs.",
    },
    "look_rim": {
        "kind": "bool",
        "default": True,
        "env": "FRIDAY_LOOK_RIM",
        "group": "persona",
        "label": "Screen look glow",
        "help": "Orange glow on all four screen edges while Friday is capturing or describing your desktop.",
    },
    "skill_proposals": {
        "kind": "bool",
        "default": False,
        "env": "SKILL_PROPOSALS",
        "group": "agent",
        "label": "Auto skill proposals",
        "help": "After successful runs, draft instruction-only skills into proposals (owner must approve). Off by default.",
    },
    "dream_mode": {
        "kind": "bool",
        "default": False,
        "env": "FRIDAY_DREAM_MODE",
        "group": "agent",
        "label": "Dream mode (diary proposals)",
        "help": "Opt-in background diary synthesis notes — never silent memory writes. Off by default.",
    },
    "presence_skin": {
        "kind": "str",
        "default": "friday",
        "group": "presence",
        "label": "Callsign skin",
        "help": "Active presence pack (voice + HUD + tone). Create custom callsigns on Systems → Presence.",
    },
    "avatar_lipsync": {
        "kind": "bool",
        "default": True,
        "env": "FRIDAY_AVATAR_LIPSYNC",
        "group": "presence",
        "label": "Talking video while speaking",
        "help": "When the active callsign has an uploaded talking-head clip, play it (muted, looped) with TTS. Upload clips on Systems → Presence.",
    },
    "avatar_engine": {
        "kind": "choice",
        "default": "auto",
        "choices": ["auto", "still", "talking"],
        "env": "FRIDAY_AVATAR_ENGINE",
        "group": "presence",
        "label": "Avatar engine",
        "help": "auto/talking = use uploaded talking video when present. still = portrait only. (Wav2Lip retired from the default path.)",
    },
}

_GROUPS = [
    ("persona", "Persona"),
    ("presence", "Presence / avatar"),
    ("agent", "Agent"),
    ("safety", "Safety"),
    ("voice", "Voice"),
    ("models", "Models"),
    ("perf", "Performance"),
    ("cad", "CAD / FreeCAD"),
    ("channels", "Channels / integrations"),
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


def is_secret(key: str) -> bool:
    spec = SCHEMA.get(key) or {}
    return bool(spec.get("secret")) or spec.get("kind") == "secret"


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
    # str + secret
    s = str(raw).strip()
    if kind == "secret":
        return s  # empty allowed (clears)
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
    """Merge UI patch into prefs. Unknown keys ignored. None deletes key (fall back to env/default).

    Secrets: empty string clears; SECRET_MASK / SECRET_KEEP leaves the stored value unchanged.
    """
    data = load_raw()
    for key, val in patch.items():
        if key not in SCHEMA:
            continue
        if val is None:
            data.pop(key, None)
            continue
        if is_secret(key):
            s = str(val).strip() if val is not None else ""
            if s in ("",):
                data.pop(key, None)
                continue
            if s in (SECRET_MASK, SECRET_KEEP):
                continue  # keep existing
            data[key] = _coerce(SCHEMA[key], s)
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
    """Full Systems payload: groups, effective values, sources, schema.

    Secret values are never returned in plaintext — only a mask when set.
    """
    items = []
    for key, spec in SCHEMA.items():
        effective = get(key)
        secret = is_secret(key)
        has_secret = bool(str(effective or "").strip()) if secret else False
        if secret:
            display = SECRET_MASK if has_secret else ""
            default_out = ""
        else:
            display = effective
            default_out = deepcopy(spec["default"])
        items.append(
            {
                "key": key,
                "value": display,
                "default": default_out,
                "source": source_of(key),
                "kind": spec["kind"],
                "choices": list(spec.get("choices") or []),
                "group": spec["group"],
                "label": spec["label"],
                "help": spec.get("help") or "",
                "restart": bool(spec.get("restart")),
                "env": spec.get("env") or "",
                "secret": secret,
                "has_secret": has_secret if secret else False,
            }
        )
    return {
        "groups": [{"id": gid, "label": label} for gid, label in _GROUPS],
        "items": items,
        "path": str(_path()),
    }
