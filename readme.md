# Project Friday

A vision-driven autonomous desktop and browser agent. Friday watches your screen with a local vision model (**qwen2.5vl:7b-q4_K_M** by default), then repeatedly observes, thinks, and takes exactly one human-like action — clicking, typing, scrolling, navigating — until your objective is done.

It does not run scripted action chains. Every action is based on the latest visual observation.

---

## How It Thinks

```
Observe screen
      ↓
Understand current UI
      ↓
Compare with objective
      ↓
Decide ONE best action
      ↓
Execute that action
      ↓
Wait for the UI to respond
      ↓
Observe again  ←─── until COMPLETE
```

If reality differs from expectations (popups, loaders, layout changes, login walls), Friday re-plans from what it sees. When it lacks factual knowledge, it can open a search tab, extract what it needs, and return to the original task.

---

## Architecture

```
friday/
├── agent/          # Observe → decide → act loop, session memory, planner
├── vision/         # Live screen feed + image preprocessing
├── actions/        # Action catalog, executor, coordinates, aim verification
├── models/         # Ollama VLM client + cloud fallback + response parser
├── knowledge/      # Web knowledge search when uncertain
├── safety/         # Human-in-the-loop gate for risky actions
└── ui/             # Overlay panel, aim cursor, Win32 helpers
```

Vision is the primary source of truth. The agent does not rely on DOM selectors — it looks at the screen the way a person would.

Optional cloud fallback (Gemini / OpenAI) kicks in only if the local model fails.

---

## Interaction Capabilities

| Category | Actions |
|----------|---------|
| Pointer | `CLICK`, `DOUBLE_CLICK`, `RIGHT_CLICK`, `MIDDLE_CLICK`, `HOVER`, `MOUSE_MOVE`, `MOUSE_DOWN`, `MOUSE_UP` |
| Drag | `DRAG`, `DRAG_DROP` |
| Scroll | `SCROLL` |
| Typing | `TYPE`, `PASTE`, `PRESS_KEY`, `HOTKEY`, `KEY_DOWN`, `KEY_UP` |
| Edit | `SELECT_ALL`, `COPY`, `CUT`, `UNDO`, `REDO`, `DELETE` |
| Apps | `WIN_SEARCH`, `SEARCH`, `SAVE_FILE` |
| Browser | `NAVIGATE`, `NEW_TAB`, `CLOSE_TAB`, `SWITCH_TAB` |
| Meta | `WAIT`, `KNOWLEDGE_SEARCH`, `COMPLETE` |

Each tick executes exactly one of these, then re-observes.

---

## Prerequisites

1. **Ollama** — https://ollama.com  
   ```bash
   ollama pull qwen2.5vl:7b-q4_K_M
   ollama serve
   ```

2. **Python 3.10+** with a virtualenv

3. **GPU** — 8GB+ VRAM recommended for the 7B vision model. For weaker machines, use `LOW_END_MODE=true` or `python main.py --low-end`.

---

## Low-end / weak hardware

Enable the built-in performance profile when RAM or GPU headroom is tight:

```bash
# .env
LOW_END_MODE=true

# or per run
python main.py --low-end
python main.py --cli --low-end "Open Notepad"
```

This automatically tunes:

| Setting | Normal | Low-end |
|---------|--------|---------|
| Frame size | 1120px | 896px |
| Encode | PNG | JPEG (82% quality) |
| Resize filter | LANCZOS | Bilinear |
| Preview FPS | 2 | 1 |
| Aim verify | on | off |
| Model output cap | 4096 tokens | 2048 tokens |

You can still override any individual variable in `.env`. For even lighter inference, try a smaller Ollama model such as `qwen2.5vl:3b`.

---

## Installation

```bash
git clone https://github.com/your-org/project-friday.git
cd project-friday

python -m venv friday_env
friday_env\Scripts\activate        # Windows
# source friday_env/bin/activate   # Linux / macOS

pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` if needed. Defaults already target `qwen2.5vl:7b-q4_K_M`.

---

## Usage

### GUI (default)

```bash
python main.py
```

Opens the Friday Control Center:

- Enter an objective and press **Start** (or `Ctrl+Enter`)
- Watch live vision, streaming reasoning, next action, and history
- **Pause** / **Resume** / **Stop** the agent at any time
- Approve or reject risky actions in-panel

The Friday window is masked out of vision captures so the model ignores it.

### CLI

```bash
python main.py --cli
python main.py --cli "Open Notepad and type Hello from Friday"
```

---

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `MODEL` | `qwen2.5vl:7b-q4_K_M` | Ollama vision model |
| `LOW_END_MODE` | `false` | Performance profile for weak hardware |
| `PREPROCESS_WIDTH` / `HEIGHT` | `1120` | Max model input dimensions |
| `PREPROCESS_FORMAT` | `png` (`jpeg` in low-end) | Image encoding for VLM upload |
| `LIVE_MODE` | `true` | Continuous screen feed |
| `STREAM_FRAME_COUNT` | `1` | Frames per inference tick |
| `STREAM_TICK_SECONDS` | `0.5` | Pause between cycles |
| `POST_ACTION_SETTLE_SECONDS` | `0.8` | Wait after mutating actions |
| `MAX_ITERATIONS` | `60` | Safety cap on observe ticks |
| `MAX_KNOWLEDGE_SEARCHES` | `3` | Cap on knowledge-search detours |
| `AIM_VERIFY_ENABLED` | `true` | Verify click targets before clicking |
| `OVERLAY_ENABLED` | `true` | Live status overlay |
| `CLOUD_PROVIDER` | `gemini` | Fallback: `gemini` or `openai` |

---

## Safety

Risky actions (`DELETE`, and any step the model flags `risky: true`) pause for explicit operator approval — via the overlay dialog or a terminal prompt.

Never run Friday as Administrator/root unless you understand the impact of full input control.

---

## Production behavior

Each tick is a hard re-evaluation cycle:

1. Capture a clean frame (Friday UI hidden/masked)
2. Model verifies the previous action against what is visible
3. Model decides exactly one next action (strict JSON after `---ACTION---`)
4. Runtime validates the action (known name, required fields, completion evidence)
5. Execute, settle, wait for a fresh frame, then loop

Key guards:

| Guard | Default | Purpose |
|-------|---------|---------|
| `REQUIRE_FRESH_FRAME` | `true` | Do not decide on a stale post-action screenshot |
| `ALLOW_PROSE_SYNTHESIS` | `false` | Reject invented actions from malformed prose |
| `REQUIRE_COMPLETION_EVIDENCE` | `true` | COMPLETE needs on-screen proof |
| `HIDE_UI_FROM_CAPTURE` | `true` | Hide overlay/markers before grabs + mask GUI |

---

## Design Principles

- **Vision first** — the screenshot is the source of truth, not scripts or selectors
- **One action at a time** — no blind multi-step chains
- **Re-evaluate every tick** — verify the last action before choosing the next
- **Adaptive** — high-level objective stays fixed; the path flexes to what is on screen
- **Recoverable** — popups, delays, and surprises trigger re-observation and re-planning
- **Knowledge when needed** — web search is a tool for uncertainty, not the default
- **Local-first** — screen data stays on your machine unless cloud fallback is required

---

## License

MIT License.
