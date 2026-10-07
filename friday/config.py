"""Centralized configuration loaded from environment variables."""

from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv()


def _env_bool(key: str, default: str = "false") -> bool:
    return os.getenv(key, default).lower() in ("1", "true", "yes")


def _env_default(key: str, normal: str, low_end: str) -> str:
    """Pick a default based on LOW_END_MODE when the key is unset."""
    if key in os.environ:
        return os.environ[key]
    return low_end if LOW_END_MODE else normal


# ---------------------------------------------------------------------------
# Performance profile — set LOW_END_MODE=true or pass --low-end on the CLI
# ---------------------------------------------------------------------------

LOW_END_MODE = _env_bool("LOW_END_MODE")

# ---------------------------------------------------------------------------
# Vision model (local-first via Ollama)
# ---------------------------------------------------------------------------

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_CHAT_URL = f"{OLLAMA_HOST}/api/chat"
OLLAMA_GENERATE_URL = f"{OLLAMA_HOST}/api/generate"

MODEL_NAME = os.getenv(
    "MODEL",
    os.getenv("LOCAL_MODEL", "qwen2.5vl:7b-q4_K_M"),
)
MODEL_KEEP_ALIVE = os.getenv("MODEL_KEEP_ALIVE", "-1")
# Decision responses are short (~300 tokens); a low cap stops runaway rambling.
MODEL_NUM_PREDICT = int(_env_default("MODEL_NUM_PREDICT", "1024", "768"))
# Deterministic sampling for reliable action JSON.
MODEL_TEMPERATURE = float(os.getenv("MODEL_TEMPERATURE", "0.2"))
MODEL_TOP_P = float(os.getenv("MODEL_TOP_P", "0.9"))
MODEL_NUM_CTX = int(os.getenv("MODEL_NUM_CTX", "8192"))
# auto | true | false — native thinking mode for models that support it.
MODEL_THINK = os.getenv("MODEL_THINK", "false").lower()

# Coordinate space the vision model grounds in:
#   pixel    — absolute pixels of the resized image (qwen2.5-vl)
#   grid1000 — normalized 0–1000 grid (qwen3-generation)
#   auto     — detect from the model name
MODEL_COORD_SPACE = os.getenv("MODEL_COORD_SPACE", "pixel").lower()

_GRID_MODEL_PREFIXES = ("qwen3", "qwen3.5", "qwen3.6", "qwen3-vl", "mai-ui")
_PIXEL_MODEL_PREFIXES = ("qwen2.5vl", "qwen2.5-vl", "qwen2vl", "llava", "minicpm")


def resolve_coord_space() -> str:
    """Which coordinate convention the current model uses for grounding."""
    if MODEL_COORD_SPACE in ("pixel", "grid1000"):
        return MODEL_COORD_SPACE
    name = MODEL_NAME.lower()
    if any(name.startswith(p) for p in _PIXEL_MODEL_PREFIXES):
        return "pixel"
    if any(name.startswith(p) for p in _GRID_MODEL_PREFIXES):
        return "grid1000"
    return "pixel"

CLOUD_PROVIDER = os.getenv("CLOUD_PROVIDER", "gemini")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# ---------------------------------------------------------------------------
# Live vision feed
# ---------------------------------------------------------------------------

LIVE_MODE = _env_bool("LIVE_MODE", "true")
LIVE_PREVIEW_FPS = float(_env_default("LIVE_PREVIEW_FPS", "2", "1"))
# Min seconds between GUI live-frame events (0 = every captured frame).
GUI_LIVE_EMIT_INTERVAL = float(_env_default("GUI_LIVE_EMIT_INTERVAL", "0", "0.5"))
STREAM_USE_VIDEO = _env_bool("STREAM_USE_VIDEO", "false")
STREAM_VIDEO_SECONDS = float(os.getenv("STREAM_VIDEO_SECONDS", "2"))
STREAM_VIDEO_FPS = float(_env_default("STREAM_VIDEO_FPS", "2", "1.5"))
STREAM_FRAME_COUNT = max(1, int(os.getenv("STREAM_FRAME_COUNT", "1")))
STREAM_TICK_SECONDS = float(_env_default("STREAM_TICK_SECONDS", "0.5", "0.75"))
POST_ACTION_SETTLE_SECONDS = float(_env_default("POST_ACTION_SETTLE_SECONDS", "0.8", "1.0"))

# ---------------------------------------------------------------------------
# Context / memory
# ---------------------------------------------------------------------------

CONTEXT_SUMMARIZE_EVERY = int(_env_default("CONTEXT_SUMMARIZE_EVERY", "8", "12"))
CONTEXT_RECENT_ACTIONS = int(os.getenv("CONTEXT_RECENT_ACTIONS", "5"))

# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------

MAX_ITERATIONS = int(os.getenv("MAX_ITERATIONS", "60"))
MAX_EMPTY_DECISIONS = int(os.getenv("MAX_EMPTY_DECISIONS", "4"))
MAX_KNOWLEDGE_SEARCHES = int(os.getenv("MAX_KNOWLEDGE_SEARCHES", "3"))
# Require a new frame after each action before the next decide tick.
REQUIRE_FRESH_FRAME = _env_bool("REQUIRE_FRESH_FRAME", "true")
# Reject invented actions from prose when JSON is missing (production default).
ALLOW_PROSE_SYNTHESIS = _env_bool("ALLOW_PROSE_SYNTHESIS", "false")
# Reject COMPLETE unless the model cites visible completion evidence.
REQUIRE_COMPLETION_EVIDENCE = _env_bool("REQUIRE_COMPLETION_EVIDENCE", "true")

# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------

RISKY_ACTIONS = frozenset({"DELETE", "FORMAT", "EXECUTE_SCRIPT", "BROWSER_MUTATION", "RUN_SHELL"})

# ---------------------------------------------------------------------------
# Display / UI
# ---------------------------------------------------------------------------

PRIMARY_MONITOR_INDEX = 1
OVERLAY_ENABLED = _env_bool("OVERLAY_ENABLED", "true")
USE_OVERLAY_APPROVAL = _env_bool("USE_OVERLAY_APPROVAL", "true")
HIDE_UI_FROM_CAPTURE = _env_bool("HIDE_UI_FROM_CAPTURE", "true")

AIM_VERIFY_ENABLED = _env_bool("AIM_VERIFY_ENABLED", "false" if LOW_END_MODE else "true")
AIM_VERIFY_MAX_ROUNDS = int(_env_default("AIM_VERIFY_MAX_ROUNDS", "4", "2"))
AIM_VERIFY_SETTLE_MS = int(_env_default("AIM_VERIFY_SETTLE_MS", "450", "350"))
# When true, an unverified target is NOT clicked (avoids blind misclicks that
# land on the wrong window). The loop re-observes and re-aims instead.
AIM_VERIFY_STRICT = _env_bool("AIM_VERIFY_STRICT", "true")
# Stop the run after this many consecutive skipped/errored actions to avoid
# burning GPU in a stuck loop. 0 disables the guard.
MAX_STUCK_ACTIONS = int(os.getenv("MAX_STUCK_ACTIONS", "8"))

CLICK_MARKER_ENABLED = _env_bool("CLICK_MARKER_ENABLED", "true")
CLICK_MARKER_DURATION = float(os.getenv("CLICK_MARKER_DURATION", "4"))

# ---------------------------------------------------------------------------
# Image preprocessing
# ---------------------------------------------------------------------------

PREPROCESS_TARGET_SIZE = (
    int(_env_default("PREPROCESS_WIDTH", "1120", "896")),
    int(_env_default("PREPROCESS_HEIGHT", "1120", "896")),
)
# png | jpeg — JPEG is much smaller/faster for VLM upload on weak hardware.
PREPROCESS_FORMAT = _env_default("PREPROCESS_FORMAT", "png", "jpeg").lower()
PREPROCESS_JPEG_QUALITY = int(_env_default("PREPROCESS_JPEG_QUALITY", "90", "82"))
# lanczos | bilinear | nearest — bilinear is a good speed/quality tradeoff.
PREPROCESS_RESAMPLE = _env_default("PREPROCESS_RESAMPLE", "lanczos", "bilinear").lower()
# auto | true | false — skip keeping PIL frames in the ring buffer unless needed.
STORE_FRAME_PIL = _env_default("STORE_FRAME_PIL", "auto", "false").lower()

# ---------------------------------------------------------------------------
# Assistant / multi-model (16GB-aware)
# ---------------------------------------------------------------------------

VISION_MODEL = os.getenv("VISION_MODEL", MODEL_NAME)
CHAT_MODEL = os.getenv("CHAT_MODEL", "")  # empty → reuse VISION_MODEL
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")
# Chat replies stay short — big caps make VL feel sluggish.
CHAT_NUM_PREDICT = int(os.getenv("CHAT_NUM_PREDICT", "256"))
CHAT_NUM_CTX = int(os.getenv("CHAT_NUM_CTX", "4096"))
# Keyword skill routing is fast; set true to also score via embeddings.
SKILL_EMBED_ROUTE = _env_bool("SKILL_EMBED_ROUTE", "false")
# Skip RAG lookup on normal chat (memory skill / remember phrases still use it).
CHAT_RAG_ENABLED = _env_bool("CHAT_RAG_ENABLED", "false")
# Indexing every assistant turn into Chroma adds an embed call — off by default.
INDEX_CHAT_TURNS = _env_bool("INDEX_CHAT_TURNS", "false")
DATA_DIR = os.getenv(
    "FRIDAY_DATA_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"),
)
WORKSPACE_DIR = os.getenv(
    "FRIDAY_WORKSPACE",
    os.path.join(DATA_DIR, "workspace"),
)
CHROMA_DIR = os.path.join(DATA_DIR, "chroma")
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.getenv("FRIDAY_CONFIG_DIR", os.path.join(_REPO_ROOT, "config"))
POLICY_PATH = os.getenv("FRIDAY_POLICY_FILE", os.path.join(CONFIG_DIR, "policy.yaml"))
MCP_CONFIG_PATH = os.getenv("FRIDAY_MCP_CONFIG", os.path.join(CONFIG_DIR, "mcp_servers.yaml"))
AUDIT_LOG_PATH = os.getenv("FRIDAY_AUDIT_LOG", os.path.join(DATA_DIR, "audit", "tool_calls.jsonl"))
# Seconds a confirm-tier call waits for the owner before it is denied (fail closed).
APPROVAL_TIMEOUT_SECONDS = float(os.getenv("FRIDAY_APPROVAL_TIMEOUT", "120"))
CONVERSATIONS_DIR = os.path.join(DATA_DIR, "conversations")
TASKS_DB = os.path.join(DATA_DIR, "tasks.sqlite")
SERVER_HOST = os.getenv("FRIDAY_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("FRIDAY_PORT", "8787"))
# HTTPS for the phone mic (HTTP on a LAN IP is not a secure context).
SERVER_TLS_PORT = int(os.getenv("FRIDAY_TLS_PORT", str(SERVER_PORT + 1)))


def ui_host(bind: str | None = None) -> str:
    """Host a browser can open. ``0.0.0.0`` / ``::`` mean listen-on-all, not a URL."""
    h = (SERVER_HOST if bind is None else bind).strip()
    if h in ("0.0.0.0", "::", "", "*"):
        return "127.0.0.1"
    return h


# Required (and enforced at startup) when FRIDAY_HOST is not a loopback address.
API_TOKEN = os.getenv("FRIDAY_API_TOKEN", "").strip()
# Extra Host header names accepted by the request guard (e.g. a LAN name behind a TLS proxy).
# Exact extra browser origins, comma separated. Dev only: set to the Vite dev server,
# e.g. FRIDAY_ALLOWED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
EXTRA_ALLOWED_ORIGINS = [o for o in os.getenv("FRIDAY_ALLOWED_ORIGINS", "").split(",") if o.strip()]
EXTRA_ALLOWED_HOSTS = [h for h in os.getenv("FRIDAY_ALLOWED_HOSTS", "").split(",") if h.strip()]
SKILLS_DIR = os.getenv(
    "FRIDAY_SKILLS_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "skills", "builtin"),
)
MAX_TOOL_STEPS = int(os.getenv("MAX_TOOL_STEPS", "8"))
VOICE_STT_MODEL = os.getenv("VOICE_STT_MODEL", "large-v3-turbo")   # provisional; accuracy on owner's voice UNVERIFIED
VOICE_TTS_VOICE = os.getenv("VOICE_TTS_VOICE", "en-IE-EmilyNeural")
VOICE_ENABLED = _env_bool("VOICE_ENABLED", "true")
SHELL_TOOLS_ENABLED = _env_bool("SHELL_TOOLS_ENABLED", "false")

# Back-compat aliases
LOCAL_MODEL_NAME = MODEL_NAME
OLLAMA_API_URL = OLLAMA_GENERATE_URL
NPU_PREPROCESSING = False  # Pillow resize only; see friday.vision.preprocessor


def resolve_chat_model() -> str:
    return (CHAT_MODEL or VISION_MODEL or MODEL_NAME).strip()


def ensure_data_dirs() -> None:
    for path in (DATA_DIR, WORKSPACE_DIR, CHROMA_DIR, CONVERSATIONS_DIR):
        os.makedirs(path, exist_ok=True)


def should_store_frame_pil() -> bool:
    if STORE_FRAME_PIL == "auto":
        return STREAM_USE_VIDEO
    return STORE_FRAME_PIL in ("1", "true", "yes")


if LOW_END_MODE:
    print(
        "[Friday] Low-end mode: "
        f"{PREPROCESS_TARGET_SIZE[0]}px frames, {PREPROCESS_FORMAT} encode, "
        f"{PREPROCESS_RESAMPLE} resize, aim_verify={AIM_VERIFY_ENABLED}"
    )
