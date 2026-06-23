import os
from dotenv import load_dotenv

load_dotenv()

# Local model config
OLLAMA_API_URL = "http://localhost:11434/api/generate"
LOCAL_MODEL_NAME = os.getenv("LOCAL_MODEL", "minicpm-v")

# Cloud fallback config
CLOUD_PROVIDER = os.getenv("CLOUD_PROVIDER", "gemini")  # "gemini" or "openai"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# Safety
RISKY_ACTIONS = ["DELETE", "FORMAT", "EXECUTE_SCRIPT", "BROWSER_MUTATION"]

# Display
PRIMARY_MONITOR_INDEX = 1