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
    os.getenv("LOCAL_MODEL", "qwen3.5:4b"),
)
MODEL_KEEP_ALIVE = os.getenv("MODEL_KEEP_ALIVE", "-1")
# Decision responses are short (~300 tokens); a low cap stops runaway rambling.
MODEL_NUM_PREDICT = int(_env_default("MODEL_NUM_PREDICT", "1024", "768"))
# Deterministic sampling for action JSON. Overrides model-card defaults
# (qwen3.5 ships with temperature=1.0 / presence_penalty=1.5 — bad for JSON).
MODEL_TEMPERATURE = float(os.getenv("MODEL_TEMPERATURE", "0.2"))
MODEL_TOP_P = float(os.getenv("MODEL_TOP_P", "0.9"))
MODEL_NUM_CTX = int(os.getenv("MODEL_NUM_CTX", "8192"))
# auto | true | false — native thinking mode for models that support it.
# Off by default: it roughly doubles per-tick latency for little gain here.
MODEL_THINK = os.getenv("MODEL_THINK", "false").lower()

# Coordinate space the vision model grounds in:
#   pixel    — absolute pixels of the resized image (qwen2.5-vl convention)
#   grid1000 — normalized 0–1000 grid (qwen3-generation convention)
#   auto     — detect from the model name
MODEL_COORD_SPACE = os.getenv("MODEL_COORD_SPACE", "auto").lower()

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

RISKY_ACTIONS = frozenset({"DELETE", "FORMAT", "EXECUTE_SCRIPT", "BROWSER_MUTATION"})

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

# Back-compat aliases
LOCAL_MODEL_NAME = MODEL_NAME
OLLAMA_API_URL = OLLAMA_GENERATE_URL
NPU_PREPROCESSING = False  # Pillow resize only; see friday.vision.preprocessor


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
