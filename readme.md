# Project Friday

A Jarvis-inspired, screen-aware desktop automation agent built on a hybrid local-first AI architecture. Friday captures your screen, sends it to a vision model alongside your task, and executes a structured multi-step plan — clicking, typing, scrolling, and pasting — autonomously.

Designed to run primarily on local hardware via Ollama, with transparent fallback to cloud providers (Gemini, OpenAI) when the local model needs backup.

---

## Core Principles

- **Local-first**: Your screen data stays on your machine by default. The cloud is a fallback, not the default.
- **Structured execution**: Every AI response is a typed action plan — no freeform command parsing, no ambiguity.
- **Human-in-the-loop safety**: Any destructive or irreversible action pauses execution and requires your explicit approval before proceeding.
- **Provider-agnostic**: Swap local models or cloud providers by changing a single environment variable.
- **Open and extensible**: Every layer is a standalone module. Add new actions, new providers, or new safety rules without touching the core loop.

---

## Architecture Overview

```
User Task (text)
      |
      v
Screen Capture (mss)
      |
      v
Router (local first, cloud fallback)
      |
      +-------> Local VLM via Ollama (RTX GPU)
      |               |
      |         [FALLBACK_TO_CLOUD]
      |               |
      +-------> Cloud Model (Gemini / OpenAI / other)
                      |
                      v
             Structured JSON Plan
             {
               "message": "What I am doing",
               "steps": [
                 { "action": "CLICK", "x": 940, "y": 320, "risky": false },
                 { "action": "TYPE", "text": "Hello", "risky": false },
                 { "action": "SCREENSHOT" },
                 ...
               ]
             }
                      |
                      v
             Step Executor (PyAutoGUI + pynput)
                      |
               [risky == true] --> Safety Gate --> Human Approval
```

---

## Supported Actions

| Action       | Description                                                  | Required Fields          |
|--------------|--------------------------------------------------------------|--------------------------|
| `CLICK`      | Left-click at a screen coordinate                            | `x`, `y`                 |
| `HOVER`      | Move mouse to a coordinate without clicking                  | `x`, `y`                 |
| `TYPE`       | Type a string character by character                         | `text`                   |
| `PASTE`      | Copy text to clipboard and paste via Ctrl+V                  | `text`                   |
| `SCROLL`     | Scroll up or down at a coordinate                            | `direction`, `x`, `y`    |
| `SEARCH`     | Open in-app search (Ctrl+F) and enter a query                | `text`                   |
| `DRAG`       | Click and drag between two coordinates                       | `x`, `y`, `x2`, `y2`     |
| `WAIT`       | Pause for a fixed duration                                   | `duration` (seconds)     |
| `SCREENSHOT` | Capture a fresh screen state before continuing               | —                        |
| `DELETE`     | Select all and delete (always gated through safety approval) | —                        |
| `COMPLETE`   | Signal that the task is fully done                           | —                        |

---

## Recommended Hardware

Friday is designed to run well on consumer-grade hardware with a modern GPU.

| Component        | Minimum               | Recommended                        |
|------------------|-----------------------|------------------------------------|
| GPU              | 6GB VRAM (NVIDIA)     | 8GB+ GDDR6X/GDDR7 (RTX 40/50 series) |
| CPU              | Any modern 6-core     | Ryzen 7 / Core i7, NPU optional    |
| RAM              | 16GB DDR4             | 32GB DDR5                          |
| Storage          | SSD                   | NVMe Gen4                          |
| OS               | Windows 10 / Ubuntu 22| Windows 11 / Ubuntu 24             |

The local VLM runs entirely on your GPU. No internet connection is required for local-only mode.

---

## Prerequisites

### 1. Install Ollama

Download from [https://ollama.com](https://ollama.com) and install for your OS.

Pull a vision-capable model. `minicpm-v` is recommended for 8GB VRAM:

```bash
ollama pull minicpm-v
```

Alternative models (choose based on your VRAM):

| Model         | VRAM Required | Notes                          |
|---------------|---------------|--------------------------------|
| `minicpm-v`   | ~5GB          | Best balance of speed/accuracy |
| `llava`       | ~6GB          | Solid general-purpose VLM      |
| `moondream`   | ~2GB          | Lightweight, lower accuracy    |
| `llava:13b`   | ~10GB         | Higher accuracy, slower        |

Start Ollama:

```bash
ollama serve
```

### 2. Python 3.10+

```bash
python -m venv friday_env
friday_env\Scripts\activate    # Windows
source friday_env/bin/activate # Linux / macOS

pip install mss pillow httpx pyautogui pynput plyer python-dotenv google-generativeai pyperclip
```

---

## Installation

```bash
git clone https://github.com/your-org/project-friday.git
cd project-friday

python -m venv friday_env
friday_env\Scripts\activate

pip install -r requirements.txt
```

Copy the environment template:

```bash
cp .env.example .env
```

Edit `.env` with your configuration:

```env
LOCAL_MODEL=minicpm-v
CLOUD_PROVIDER=gemini
GEMINI_API_KEY=your_gemini_api_key_here
OPENAI_API_KEY=your_openai_api_key_here
```

---

## Usage

```bash
python main.py
```

Friday will prompt you for a task:

```
Enter your task for Friday: Open Notepad and type "Hello from Friday"
```

Friday then:
1. Captures your screen
2. Sends it along with the task to the local model
3. Receives a structured step plan
4. Executes each step with live console output
5. Pauses at any risky action for your approval
6. Inserts mid-plan screenshots automatically when the model requests them

---

## Project Structure

```
friday/
├── main.py                     # Entry point
├── config.py                   # Centralized config and environment loading
├── engine/
│   ├── capture.py              # Screen capture via mss
│   ├── local_model.py          # Ollama VLM client
│   ├── cloud_model.py          # Gemini and OpenAI adapters
│   ├── router.py               # Local-first routing with cloud fallback
│   ├── executor.py             # Action execution (PyAutoGUI + pynput)
│   └── safety.py               # Risk detection and human-in-the-loop gate
├── memory/
│   └── approved_patterns.json  # Persisted operator-approved action patterns
├── .env                        # Your secrets — never commit this
├── .env.example                # Template for contributors
├── requirements.txt
└── README.md
```

---

## Configuration Reference

| Variable        | Default       | Description                                         |
|-----------------|---------------|-----------------------------------------------------|
| `LOCAL_MODEL`   | `minicpm-v`   | Ollama model name to use for local inference        |
| `CLOUD_PROVIDER`| `gemini`      | Cloud fallback provider: `gemini` or `openai`       |
| `GEMINI_API_KEY`| —             | Google Gemini API key                               |
| `OPENAI_API_KEY`| —             | OpenAI API key (used when CLOUD_PROVIDER is openai) |

---

## Safety System

Friday enforces a two-tier safety model:

**Tier 1 — Automatic Risk Tagging**

The AI model marks any step it considers risky with `"risky": true`. Additionally, any step with action `DELETE`, `FORMAT`, `EXECUTE_SCRIPT`, or `BROWSER_MUTATION` is automatically escalated regardless of what the model says.

**Tier 2 — Human Approval Gate**

When a risky step is detected, execution halts completely. The terminal prints a full summary of the action and waits for your typed `yes` or `no` before proceeding. A rejection skips that step and continues. The loop does not resume until you respond.

Approved patterns are written to `memory/approved_patterns.json` for future reference (this is a roadmap item — see Contributing).

---

## Adding a New Cloud Provider

1. Open `engine/cloud_model.py`
2. Add a new function `_query_yourprovider(objective, base64_image) -> dict`
3. Add a branch in `query_cloud_model()` to call it
4. Add your provider name as a valid value for `CLOUD_PROVIDER` in `.env`

The function must return a dict with at minimum `steps: list` and `message: str`.

---

## Adding a New Action

1. Open `engine/executor.py`
2. Add an `elif action == "YOUR_ACTION":` branch inside `execute_step()`
3. Implement the PyAutoGUI / pynput call
4. Document it in this README under the Supported Actions table
5. If the action is inherently risky, add it to `RISKY_ACTIONS` in `config.py`

---

## Roadmap

- [ ] GUI overlay showing live step progress
- [ ] Persistent memory of approved action patterns
- [ ] Voice input for task entry (Whisper integration)
- [ ] Multi-monitor support with monitor targeting per step
- [ ] NPU-accelerated image preprocessing for AMD Ryzen AI / Intel NPU
- [ ] Web UI for remote task submission
- [ ] Session replay and audit log export
- [ ] Plugin system for custom action handlers

---

## Contributing

Contributions are welcome. Please follow these guidelines:

- Keep modules single-responsibility. `executor.py` executes. `router.py` routes. Do not mix concerns.
- Every new action must have a corresponding safety classification in `config.py`.
- Do not commit `.env` or any file containing API keys.
- Open an issue before starting work on a large feature so we can discuss approach.
- Write clear commit messages describing what changed and why.

```bash
git checkout -b feature/your-feature-name
# make your changes
git commit -m "feat: describe your change clearly"
git push origin feature/your-feature-name
# open a pull request
```

---

## Security Notes

- Friday requires mouse and keyboard control permissions. On macOS this means Accessibility permissions. On Linux you may need to add your user to the `input` group.
- Never run Friday with elevated/root privileges unless you understand what you are doing.
- The `.env` file containing your API keys must never be committed. It is already in `.gitignore`.
- All cloud API calls transmit screenshots to external servers. If your screen contains sensitive data, use local-only mode by ensuring `CLOUD_PROVIDER` is not triggered (keep your local model healthy and the routing will stay local).

---

## License

MIT License. See `LICENSE` for full text.

---

## Acknowledgments

Built on top of:
- [Ollama](https://ollama.com) — local model inference
- [mss](https://github.com/BoboTiG/python-mss) — fast cross-platform screen capture
- [PyAutoGUI](https://github.com/asweigart/pyautogui) — GUI automation
- [pynput](https://github.com/moses-palmer/pynput) — low-level input control
- [Google Generative AI SDK](https://github.com/google/generative-ai-python) — Gemini cloud fallback