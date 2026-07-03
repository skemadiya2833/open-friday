import os
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Model config — single streaming VLM
# ---------------------------------------------------------------------------

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_CHAT_URL = f"{OLLAMA_HOST}/api/chat"
OLLAMA_GENERATE_URL = f"{OLLAMA_HOST}/api/generate"

MODEL_NAME = os.getenv(
    "MODEL",
    os.getenv("LOCAL_MODEL", "qwen2.5vl:7b-q4_K_M"),
)

# Keep model loaded for the session (-1) or unload after each call (0).
MODEL_KEEP_ALIVE = os.getenv("MODEL_KEEP_ALIVE", "-1")

CLOUD_PROVIDER = os.getenv("CLOUD_PROVIDER", "gemini")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# ---------------------------------------------------------------------------
# Live mode (continuous feed — not discrete screenshot capture)
# ---------------------------------------------------------------------------

LIVE_MODE = os.getenv("LIVE_MODE", "true").lower() in ("1", "true", "yes")

# Overlay preview refresh rate (frames per second). 2–3 is plenty; higher = more CPU.
LIVE_PREVIEW_FPS = float(os.getenv("LIVE_PREVIEW_FPS", "2"))

# Send a short video clip to Qwen2.5-VL (requires ffmpeg on PATH).
# Falls back to multi-frame images if ffmpeg is unavailable.
STREAM_USE_VIDEO = os.getenv("STREAM_USE_VIDEO", "true").lower() in ("1", "true", "yes")
STREAM_VIDEO_SECONDS = float(os.getenv("STREAM_VIDEO_SECONDS", "2"))
STREAM_VIDEO_FPS = float(os.getenv("STREAM_VIDEO_FPS", "2"))

# Legacy: max still frames when video encoding is off/unavailable.
# Use 1 for reliability — multi-image requests often return empty from Qwen2.5-VL.
STREAM_FRAME_COUNT = max(1, int(os.getenv("STREAM_FRAME_COUNT", "1")))

# Pause between observe→act cycles (seconds).
STREAM_TICK_SECONDS = float(os.getenv("STREAM_TICK_SECONDS", "0.5"))

# ---------------------------------------------------------------------------
# Context summarization (prevents OOM from growing text history)
# ---------------------------------------------------------------------------

# Summarize action history every N completed actions.
CONTEXT_SUMMARIZE_EVERY = int(os.getenv("CONTEXT_SUMMARIZE_EVERY", "8"))

# Raw actions kept verbatim after each summarization pass.
CONTEXT_RECENT_ACTIONS = int(os.getenv("CONTEXT_RECENT_ACTIONS", "5"))

# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------

RISKY_ACTIONS = ["DELETE", "FORMAT", "EXECUTE_SCRIPT", "BROWSER_MUTATION"]

# ---------------------------------------------------------------------------
# Execution loop
# ---------------------------------------------------------------------------

MAX_ITERATIONS = int(os.getenv("MAX_ITERATIONS", "30"))
MAX_STEPS_PER_BATCH = int(os.getenv("MAX_STEPS_PER_BATCH", "8"))

# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

PRIMARY_MONITOR_INDEX = 1

OVERLAY_ENABLED = os.getenv("OVERLAY_ENABLED", "true").lower() in ("1", "true", "yes")
USE_OVERLAY_APPROVAL = os.getenv("USE_OVERLAY_APPROVAL", "true").lower() in (
    "1", "true", "yes",
)

HIDE_UI_FROM_CAPTURE = os.getenv("HIDE_UI_FROM_CAPTURE", "true").lower() in (
    "1", "true", "yes",
)

AIM_VERIFY_ENABLED = os.getenv("AIM_VERIFY_ENABLED", "true").lower() in (
    "1", "true", "yes",
)
AIM_VERIFY_MAX_ROUNDS = int(os.getenv("AIM_VERIFY_MAX_ROUNDS", "3"))
AIM_VERIFY_SETTLE_MS = int(os.getenv("AIM_VERIFY_SETTLE_MS", "450"))

CLICK_MARKER_ENABLED = os.getenv("CLICK_MARKER_ENABLED", "true").lower() in (
    "1", "true", "yes",
)
CLICK_MARKER_DURATION = float(os.getenv("CLICK_MARKER_DURATION", "4"))

# ---------------------------------------------------------------------------
# Image preprocessing
# ---------------------------------------------------------------------------

NPU_PREPROCESSING = os.getenv("NPU_PREPROCESSING", "true").lower() in (
    "1", "true", "yes",
)
PREPROCESS_TARGET_SIZE = (
    int(os.getenv("PREPROCESS_WIDTH", "1120")),
    int(os.getenv("PREPROCESS_HEIGHT", "1120")),
)

ALL_ACTIONS = [
    "WIN_SEARCH", "CLICK", "HOVER", "TYPE", "PASTE", "PRESS_KEY", "SCROLL",
    "SEARCH", "DRAG", "WAIT", "SCREENSHOT", "SAVE_FILE", "DELETE", "COMPLETE",
]

# Back-compat alias used by cloud_model / legacy imports
LOCAL_MODEL_NAME = MODEL_NAME
OLLAMA_API_URL = OLLAMA_GENERATE_URL
