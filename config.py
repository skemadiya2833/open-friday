import os
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Model config
# ---------------------------------------------------------------------------

OLLAMA_API_URL = "http://localhost:11434/api/generate"
LOCAL_MODEL_NAME = os.getenv("LOCAL_MODEL", "llava:7b")

CLOUD_PROVIDER = os.getenv("CLOUD_PROVIDER", "gemini")   # "gemini" or "openai"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------

# Actions that are always escalated to the human approval gate regardless of
# whether the model marks them risky or not.
RISKY_ACTIONS = ["DELETE", "FORMAT", "EXECUTE_SCRIPT", "BROWSER_MUTATION"]

# ---------------------------------------------------------------------------
# Execution loop
# ---------------------------------------------------------------------------

# Maximum number of plan-capture-execute iterations before Friday gives up.
# Prevents infinite loops when the model cannot make progress.
MAX_ITERATIONS = int(os.getenv("MAX_ITERATIONS", "30"))

# Maximum low-level action steps the model may return per screenshot cycle.
MAX_STEPS_PER_BATCH = int(os.getenv("MAX_STEPS_PER_BATCH", "8"))

# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

PRIMARY_MONITOR_INDEX = 1

OVERLAY_ENABLED = os.getenv("OVERLAY_ENABLED", "true").lower() in ("1", "true", "yes")
USE_OVERLAY_APPROVAL = os.getenv("USE_OVERLAY_APPROVAL", "true").lower() in (
    "1",
    "true",
    "yes",
)

# ---------------------------------------------------------------------------
# Image preprocessing (NPU via ONNX Runtime when available)
# ---------------------------------------------------------------------------

NPU_PREPROCESSING = os.getenv("NPU_PREPROCESSING", "true").lower() in (
    "1",
    "true",
    "yes",
)
PREPROCESS_TARGET_SIZE = (
    int(os.getenv("PREPROCESS_WIDTH", "1120")),
    int(os.getenv("PREPROCESS_HEIGHT", "1120")),
)  # max bounding box; aspect ratio is preserved

# ---------------------------------------------------------------------------
# Known action vocabulary (informational — used by router prompt builder)
# ---------------------------------------------------------------------------

ALL_ACTIONS = [
    "WIN_SEARCH",
    "CLICK",
    "HOVER",
    "TYPE",
    "PASTE",
    "PRESS_KEY",
    "SCROLL",
    "SEARCH",
    "DRAG",
    "WAIT",
    "SCREENSHOT",
    "SAVE_FILE",
    "DELETE",
    "COMPLETE",
]