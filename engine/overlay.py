"""
Tkinter floating overlay for Friday's live execution view.

Shows screenshot, model reasoning stream, plan phases, step progress,
completed-step log, and risky-action approval. Runs on a background thread
so the main loop is never blocked. Mouse/keyboard events pass through on
Windows except during approval dialogs.
"""

from __future__ import annotations

import platform
import queue
import threading
from dataclasses import dataclass, field
from typing import Any

from PIL import Image, ImageTk

# ---------------------------------------------------------------------------
# Layout constants
# ---------------------------------------------------------------------------

PANEL_W = 440
THUMB_H = 140
BASE_H = 580
LOG_H = 100
MARGIN = 16

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_overlay: "OverlayController | None" = None


def start(total_steps: int, task_name: str = "") -> None:
    global _overlay
    if _overlay is None:
        _overlay = OverlayController()
    _overlay.start(total_steps, task_name)


def update_screenshot(pil_image: Image.Image) -> None:
    if _overlay is not None:
        _overlay.update_screenshot(pil_image)


def update_plan(message: str, steps: list) -> None:
    if _overlay is not None:
        _overlay.update_plan(message, steps)


def update_strategy(
    plan_message: str,
    phases: list,
    current_phase_index: int = 0,
) -> None:
    if _overlay is not None:
        _overlay.update_strategy(plan_message, phases, current_phase_index)


def update(
    step_index: int,
    action: str,
    status: str,
    step: dict | None = None,
    task_name: str | None = None,
    iteration: int | None = None,
) -> None:
    if _overlay is not None:
        _overlay.update(
            step_index,
            action,
            status,
            step=step,
            task_name=task_name,
            iteration=iteration,
        )


def set_status(status: str) -> None:
    if _overlay is not None:
        _overlay.set_status(status)


def push_thinking(token: str) -> None:
    """
    Append a token or chunk to the live reasoning stream display.
    Call this from the model query loop as tokens arrive.
    """
    if _overlay is not None:
        _overlay.push_thinking(token)


def clear_thinking() -> None:
    """Clear the reasoning stream buffer (call before each new model query)."""
    if _overlay is not None:
        _overlay.clear_thinking()


def set_thinking(text: str) -> None:
    """Replace the reasoning stream with final reasoning text."""
    if _overlay is not None:
        _overlay.set_thinking(text)


def sync_completed_steps(history: list[str]) -> None:
    """Sync the completed-step log from session history."""
    if _overlay is not None:
        _overlay.sync_completed_steps(history)


def await_approval(step: dict) -> bool:
    if _overlay is None:
        return False
    return _overlay.await_approval(step)


def close() -> None:
    global _overlay
    if _overlay is not None:
        _overlay.close()
        _overlay = None


# ---------------------------------------------------------------------------
# Status colours and labels
# ---------------------------------------------------------------------------

STATUS_COLORS = {
    "running":              "#3b82f6",
    "thinking":             "#8b5cf6",
    "waiting":              "#f59e0b",
    "waiting for approval": "#f59e0b",
    "complete":             "#22c55e",
    "error":                "#ef4444",
    "halt":                 "#ef4444",
    "idle":                 "#6b7280",
}

STATUS_LABELS = {
    "running":              "RUNNING",
    "thinking":             "THINKING",
    "waiting":              "WAITING",
    "waiting for approval": "AWAITING APPROVAL",
    "complete":             "COMPLETE",
    "error":                "ERROR",
    "halt":                 "HALTED",
    "idle":                 "IDLE",
}


def format_action_target(step: dict | None, action: str = "") -> str:
    if not step:
        return action.upper() if action else ""

    act = (step.get("action") or action or "").upper()

    if act in ("CLICK", "DOUBLE_CLICK", "RIGHT_CLICK", "MIDDLE_CLICK", "HOVER"):
        x, y = step.get("x"), step.get("y")
        return f"{act} at ({x}, {y})" if x is not None and y is not None else act

    if act in ("TYPE", "PASTE", "SEARCH", "WIN_SEARCH"):
        text = step.get("text") or ""
        preview = text[:40] + ("..." if len(text) > 40 else "")
        return f'{act} "{preview}"'

    if act == "PRESS_KEY":
        return f"PRESS_KEY {step.get('key') or ''}"

    if act == "HOTKEY":
        keys = step.get("keys") or []
        return f"HOTKEY {'+'.join(keys)}"

    if act == "SAVE_FILE":
        name = step.get("text") or ""
        return f"SAVE_FILE {name}" if name else "SAVE_FILE (Ctrl+S)"

    if act == "SCROLL":
        direction = step.get("direction", "down")
        x, y = step.get("x"), step.get("y")
        return f"SCROLL {direction} at ({x}, {y})" if x and y else f"SCROLL {direction}"

    if act == "WAIT":
        return f"WAIT {step.get('duration', 1.5)}s"

    if act in ("DRAG", "DRAG_DROP"):
        return (
            f"{act} ({step.get('x')},{step.get('y')})"
            f" -> ({step.get('x2')},{step.get('y2')})"
        )

    if act == "DELETE":
        return "DELETE selected content"

    if act == "SCREENSHOT":
        return "SCREENSHOT (refresh)"

    if act == "COMPLETE":
        return "COMPLETE"

    desc = step.get("description") or ""
    return f"{act}: {desc}" if desc else act


def _format_phases(phases: list, current_phase_index: int, limit: int = 6) -> str:
    if not phases:
        return "No phases defined."
    lines: list[str] = []
    for i, phase in enumerate(phases[:limit]):
        title = phase.get("title") or phase.get("goal") or f"Phase {i + 1}"
        prefix = "Done" if i < current_phase_index else ("Now" if i == current_phase_index else f"  {i + 1}")
        lines.append(f"{prefix}. {title}")
    if len(phases) > limit:
        lines.append(f"  ... {len(phases) - limit} more")
    return "\n".join(lines)


def _format_upcoming_steps(plan_steps: list, step_index: int, limit: int = 4) -> str:
    if not plan_steps:
        return "No steps queued."
    remaining = plan_steps[step_index:] if step_index <= len(plan_steps) else []
    if not remaining:
        return "No steps queued."
    lines: list[str] = []
    for i, step in enumerate(remaining[:limit]):
        num = step_index + i + 1
        summary = format_action_target(step, step.get("action", ""))
        prefix = "->" if i == 0 else "  "
        lines.append(f"{prefix} {num}. {summary}")
    if len(remaining) > limit:
        lines.append(f"  ... and {len(remaining) - limit} more")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# State dataclass
# ---------------------------------------------------------------------------

@dataclass
class OverlayState:
    task_name: str = ""
    total_steps: int = 0
    step_index: int = 0
    iteration: int = 0
    action: str = ""
    description: str = ""
    status: str = "idle"
    current_target: str = ""
    message: str = ""
    plan_message: str = ""
    phases: list = field(default_factory=list)
    current_phase_index: int = 0
    plan_steps: list = field(default_factory=list)
    thumb_pil: Image.Image | None = None
    log_entries: list[str] = field(default_factory=list)
    log_expanded: bool = True
    awaiting_approval: bool = False
    approval_step: dict | None = None
    thinking_buffer: str = ""


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------

class OverlayController:
    def __init__(self) -> None:
        self._cmd_queue: queue.Queue = queue.Queue()
        self._approval_event = threading.Event()
        self._approval_result: bool = False
        self._thread: threading.Thread | None = None
        self._running = False
        self._state = OverlayState()
        self._thumb_photo: ImageTk.PhotoImage | None = None

    def start(self, total_steps: int, task_name: str = "") -> None:
        self._state.task_name = task_name
        self._state.total_steps = total_steps
        if not self._running:
            self._running = True
            self._thread = threading.Thread(target=self._run_ui, daemon=True)
            self._thread.start()

    def update_screenshot(self, pil_image: Image.Image) -> None:
        thumb = pil_image.copy()
        thumb.thumbnail((PANEL_W - 24, THUMB_H), Image.LANCZOS)
        self._cmd_queue.put({"type": "screenshot", "image": thumb})

    def update_plan(self, message: str, steps: list) -> None:
        self._cmd_queue.put({"type": "plan", "message": message or "", "steps": steps or []})

    def update_strategy(self, plan_message: str, phases: list, current_phase_index: int = 0) -> None:
        self._cmd_queue.put({
            "type": "strategy",
            "plan_message": plan_message or "",
            "phases": phases or [],
            "current_phase_index": current_phase_index,
        })

    def update(
        self,
        step_index: int,
        action: str,
        status: str,
        step: dict | None = None,
        task_name: str | None = None,
        iteration: int | None = None,
    ) -> None:
        self._cmd_queue.put({
            "type": "update",
            "step_index": step_index,
            "action": action,
            "status": status,
            "step": step,
            "task_name": task_name,
            "iteration": iteration,
        })

    def set_status(self, status: str) -> None:
        self._cmd_queue.put({"type": "set_status", "status": status})

    def push_thinking(self, token: str) -> None:
        self._cmd_queue.put({"type": "thinking_token", "token": token})

    def clear_thinking(self) -> None:
        self._cmd_queue.put({"type": "thinking_clear"})

    def set_thinking(self, text: str) -> None:
        self._cmd_queue.put({"type": "thinking_set", "text": text or ""})

    def sync_completed_steps(self, history: list[str]) -> None:
        self._cmd_queue.put({"type": "sync_log", "entries": history or []})

    def await_approval(self, step: dict) -> bool:
        self._cmd_queue.put({"type": "approval", "step": step})
        self._approval_event.wait()
        result = self._approval_result
        self._approval_event.clear()
        return result

    def close(self) -> None:
        if self._running:
            self._cmd_queue.put({"type": "close"})
            if self._thread is not None:
                self._thread.join(timeout=3)
            self._running = False

    def _set_approval_result(self, approved: bool) -> None:
        self._approval_result = approved
        self._approval_event.set()

    # -------------------------------------------------------------------------
    # UI thread
    # -------------------------------------------------------------------------

    def _run_ui(self) -> None:
        import tkinter as tk
        from tkinter import font as tkfont

        root = tk.Tk()
        root.title("Friday")
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.attributes("-alpha", 0.93)

        screen_w = root.winfo_screenwidth()

        def _position(height: int) -> None:
            root.geometry(f"{PANEL_W}x{height}+{screen_w - PANEL_W - MARGIN}+{MARGIN}")

        _position(BASE_H)

        # Colours
        bg       = "#0f0f1a"
        fg       = "#e8e8f0"
        muted    = "#7777aa"
        panel_bg = "#13131f"
        think_bg = "#0a0a18"
        gold     = "#c8a85a"

        root.configure(bg=bg)

        title_font   = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        body_font    = tkfont.Font(family="Segoe UI", size=9)
        small_font   = tkfont.Font(family="Segoe UI", size=8)
        mono_font    = tkfont.Font(family="Consolas", size=8)
        badge_font   = tkfont.Font(family="Segoe UI", size=8, weight="bold")
        think_font   = tkfont.Font(family="Segoe UI", size=9)

        # -- Task name and iteration -----------------------------------------
        task_lbl = tk.Label(root, text="", font=title_font, bg=bg, fg=fg, anchor="w")
        task_lbl.pack(fill="x", padx=12, pady=(10, 0))

        step_lbl = tk.Label(root, text="", font=body_font, bg=bg, fg=muted, anchor="w")
        step_lbl.pack(fill="x", padx=12, pady=(2, 4))

        # -- Screenshot thumbnail --------------------------------------------
        thumb_frame = tk.Frame(root, bg=panel_bg, height=THUMB_H)
        thumb_frame.pack(fill="x", padx=12)
        thumb_frame.pack_propagate(False)

        thumb_lbl = tk.Label(
            thumb_frame, text="Waiting for screenshot...",
            font=body_font, bg=panel_bg, fg=muted,
        )
        thumb_lbl.pack(expand=True)

        # -- Status badge + current action -----------------------------------
        badge_frame = tk.Frame(root, bg=bg)
        badge_frame.pack(fill="x", padx=12, pady=(8, 0))

        badge = tk.Label(
            badge_frame, text="IDLE", font=badge_font,
            bg=STATUS_COLORS["idle"], fg="#ffffff", padx=8, pady=2,
        )
        badge.pack(side="left")

        action_lbl = tk.Label(
            root, text="", font=mono_font, bg=bg, fg="#a8d8ff",
            anchor="w", wraplength=PANEL_W - 24,
        )
        action_lbl.pack(fill="x", padx=12, pady=(4, 0))

        desc_lbl = tk.Label(
            root, text="", font=body_font, bg=bg, fg=fg,
            anchor="w", wraplength=PANEL_W - 24, justify="left",
        )
        desc_lbl.pack(fill="x", padx=12, pady=(2, 0))

        # -- Live reasoning stream -------------------------------------------
        tk.Label(root, text="REASONING", font=small_font, bg=bg, fg=muted, anchor="w").pack(
            fill="x", padx=12, pady=(8, 0)
        )

        think_frame = tk.Frame(root, bg=think_bg, height=88)
        think_frame.pack(fill="x", padx=12)
        think_frame.pack_propagate(False)

        think_text = tk.Text(
            think_frame,
            font=think_font,
            bg=think_bg,
            fg="#c4b5fd",
            relief="flat",
            highlightthickness=0,
            wrap="word",
            state="disabled",
            cursor="arrow",
        )
        think_text.pack(fill="both", expand=True, padx=4, pady=4)

        # -- Phase plan ------------------------------------------------------
        tk.Label(root, text="PLAN", font=small_font, bg=bg, fg=muted, anchor="w").pack(
            fill="x", padx=12, pady=(6, 0)
        )
        phases_lbl = tk.Label(
            root, text="No phases defined.", font=mono_font,
            bg=bg, fg=gold, anchor="nw", justify="left", wraplength=PANEL_W - 24,
        )
        phases_lbl.pack(fill="x", padx=12, pady=(0, 2))

        # -- Next actions ----------------------------------------------------
        tk.Label(root, text="NEXT ACTIONS", font=small_font, bg=bg, fg=muted, anchor="w").pack(
            fill="x", padx=12, pady=(4, 0)
        )
        upcoming_lbl = tk.Label(
            root, text="No steps queued.", font=mono_font,
            bg=bg, fg=gold, anchor="nw", justify="left", wraplength=PANEL_W - 24,
        )
        upcoming_lbl.pack(fill="x", padx=12, pady=(0, 2))

        # -- Model message ---------------------------------------------------
        tk.Label(root, text="MODEL SAYS", font=small_font, bg=bg, fg=muted, anchor="w").pack(
            fill="x", padx=12, pady=(4, 0)
        )
        message_lbl = tk.Label(
            root, text="—", font=body_font, bg=bg, fg=fg,
            anchor="w", wraplength=PANEL_W - 24, justify="left",
        )
        message_lbl.pack(fill="x", padx=12, pady=(0, 2))

        # -- Completed steps log ---------------------------------------------
        log_toggle = tk.Button(
            root, text="- Completed steps", font=body_font,
            bg="#1e1e35", fg=muted, relief="flat",
            activebackground="#2a2a50", activeforeground=fg,
            anchor="w", padx=8, command=lambda: None,
        )
        log_toggle.pack(fill="x", padx=8, pady=(4, 0))

        log_frame = tk.Frame(root, bg=panel_bg, height=LOG_H)
        log_frame.pack(fill="x", padx=8, pady=(2, 8))
        log_frame.pack_propagate(False)

        log_scroll = tk.Scrollbar(log_frame, orient="vertical")
        log_list = tk.Listbox(
            log_frame, font=mono_font, bg=panel_bg, fg="#88cc88",
            relief="flat", highlightthickness=0,
            selectbackground="#303060",
            yscrollcommand=log_scroll.set,
            activestyle="none",
        )
        log_scroll.config(command=log_list.yview)
        log_scroll.pack(side="right", fill="y")
        log_list.pack(fill="both", expand=True, padx=4, pady=4)

        # -- Approval panel --------------------------------------------------
        approval_frame = tk.Frame(root, bg="#2a1a10", relief="flat")
        approval_lbl = tk.Label(
            approval_frame, text="", font=body_font,
            bg="#2a1a10", fg="#ffcc88",
            wraplength=PANEL_W - 24, justify="left",
        )
        approval_lbl.pack(fill="x", padx=10, pady=(8, 4))

        btn_row = tk.Frame(approval_frame, bg="#2a1a10")
        btn_row.pack(fill="x", padx=10, pady=(0, 8))

        tk.Button(
            btn_row, text="Approve", font=body_font,
            bg="#166534", fg="#ffffff", relief="flat",
            activebackground="#15803d", padx=12, pady=4,
            command=lambda: self._set_approval_result(True),
        ).pack(side="left", padx=(0, 8))

        tk.Button(
            btn_row, text="Reject", font=body_font,
            bg="#7f1d1d", fg="#ffffff", relief="flat",
            activebackground="#991b1b", padx=12, pady=4,
            command=lambda: self._set_approval_result(False),
        ).pack(side="left")

        # -- Windows click-through helpers -----------------------------------
        def _apply_click_through() -> None:
            if platform.system() != "Windows":
                return
            try:
                import ctypes
                hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
                GWL_EXSTYLE    = -20
                WS_EX_LAYERED  = 0x00080000
                WS_EX_TRANSPARENT = 0x00000020
                WS_EX_TOPMOST  = 0x00000008
                style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                ctypes.windll.user32.SetWindowLongW(
                    hwnd, GWL_EXSTYLE,
                    style | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOPMOST,
                )
            except Exception:
                pass

        def _disable_click_through() -> None:
            if platform.system() != "Windows":
                return
            try:
                import ctypes
                hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
                GWL_EXSTYLE    = -20
                WS_EX_LAYERED  = 0x00080000
                WS_EX_TOPMOST  = 0x00000008
                WS_EX_TRANSPARENT = 0x00000020
                style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                ctypes.windll.user32.SetWindowLongW(
                    hwnd, GWL_EXSTYLE,
                    (style | WS_EX_LAYERED | WS_EX_TOPMOST) & ~WS_EX_TRANSPARENT,
                )
            except Exception:
                pass

        def _current_height() -> int:
            extra = 0
            if not self._state.log_expanded:
                extra -= LOG_H + 8
            if self._state.awaiting_approval:
                extra += 110
            return BASE_H + extra

        def _toggle_log() -> None:
            self._state.log_expanded = not self._state.log_expanded
            log_toggle.config(text=("- Completed steps" if self._state.log_expanded else "+ Completed steps"))
            if self._state.log_expanded:
                log_frame.pack(fill="x", padx=8, pady=(2, 8))
            else:
                log_frame.pack_forget()
            _position(_current_height())

        log_toggle.config(command=_toggle_log)

        # -- Refresh helpers -------------------------------------------------
        def _refresh_thumb() -> None:
            pil = self._state.thumb_pil
            if pil is None:
                thumb_lbl.config(image="", text="Waiting for screenshot...")
                self._thumb_photo = None
                return
            self._thumb_photo = ImageTk.PhotoImage(pil)
            thumb_lbl.config(image=self._thumb_photo, text="")

        def _append_thinking(text: str) -> None:
            think_text.config(state="normal")
            think_text.insert("end", text)
            # Keep buffer under ~600 chars so it stays readable
            content = think_text.get("1.0", "end")
            if len(content) > 700:
                think_text.delete("1.0", f"1.{len(content) - 600}")
            think_text.see("end")
            think_text.config(state="disabled")

        def _clear_thinking() -> None:
            think_text.config(state="normal")
            think_text.delete("1.0", "end")
            think_text.config(state="disabled")

        def _set_thinking(text: str) -> None:
            think_text.config(state="normal")
            think_text.delete("1.0", "end")
            think_text.insert("1.0", text)
            think_text.see("end")
            think_text.config(state="disabled")

        def _refresh_log() -> None:
            log_list.delete(0, "end")
            for entry in self._state.log_entries:
                log_list.insert("end", entry)
            if self._state.log_entries:
                log_list.see("end")

        def _refresh_ui() -> None:
            s = self._state
            task_lbl.config(text=s.task_name or "Friday")

            if s.iteration > 0 and s.total_steps > 0:
                step_lbl.config(text=f"Iteration {s.iteration}  |  Step {s.step_index}/{s.total_steps}")
            elif s.iteration > 0:
                step_lbl.config(text=f"Iteration {s.iteration}")
            elif s.total_steps > 0:
                step_lbl.config(text=f"Step {s.step_index}/{s.total_steps}")
            else:
                step_lbl.config(text="")

            action_lbl.config(text=s.current_target or s.action.upper())
            desc_lbl.config(text=s.description or "")

            color = STATUS_COLORS.get(s.status, STATUS_COLORS["running"])
            label = STATUS_LABELS.get(s.status, s.status.upper())
            badge.config(text=label, bg=color)

            message_lbl.config(text=s.message or "—")
            phases_lbl.config(text=_format_phases(s.phases, s.current_phase_index))
            upcoming_lbl.config(text=_format_upcoming_steps(s.plan_steps, s.step_index))

            log_list.delete(0, "end")
            for entry in s.log_entries:
                log_list.insert("end", entry)
            if s.log_entries:
                log_list.see("end")

            _refresh_thumb()

            if s.awaiting_approval:
                step = s.approval_step or {}
                summary = format_action_target(step, step.get("action", ""))
                approval_lbl.config(
                    text=f"Risky action — approval required:\n{summary}\n{step.get('description', '')}"
                )
                approval_frame.pack(fill="x", padx=8, pady=(6, 8))
                _disable_click_through()
            else:
                approval_frame.pack_forget()
                _apply_click_through()

            _position(_current_height())

        # -- Command dispatcher ----------------------------------------------
        def _process_cmd(cmd: dict[str, Any]) -> None:
            t = cmd.get("type")

            if t == "close":
                root.quit()
                return

            if t == "screenshot":
                self._state.thumb_pil = cmd["image"]
                _refresh_ui()
                return

            if t == "plan":
                self._state.message = cmd["message"]
                self._state.plan_steps = cmd["steps"]
                self._state.step_index = 0
                _refresh_ui()
                return

            if t == "strategy":
                self._state.plan_message = cmd["plan_message"]
                self._state.phases = cmd["phases"]
                self._state.current_phase_index = cmd["current_phase_index"]
                _refresh_ui()
                return

            if t == "set_status":
                self._state.status = cmd["status"]
                _refresh_ui()
                return

            if t == "thinking_token":
                _append_thinking(cmd["token"])
                return

            if t == "thinking_clear":
                _clear_thinking()
                return

            if t == "thinking_set":
                _set_thinking(cmd.get("text", ""))
                return

            if t == "sync_log":
                self._state.log_entries = [
                    f"{i + 1}. {entry}" for i, entry in enumerate(cmd.get("entries", []))
                ]
                _refresh_log()
                return

            if t == "update":
                new_index  = cmd["step_index"]
                new_action = cmd["action"]
                new_status = cmd["status"]
                step       = cmd.get("step")

                if cmd.get("task_name") is not None:
                    self._state.task_name = cmd["task_name"]
                if cmd.get("iteration") is not None:
                    self._state.iteration = cmd["iteration"]
                if step and step.get("description"):
                    self._state.description = step["description"]

                self._state.step_index    = new_index
                self._state.action        = new_action
                self._state.status        = new_status
                if step:
                    self._state.current_target = format_action_target(step, new_action)
                self._state.awaiting_approval = False
                _refresh_ui()
                return

            if t == "approval":
                step = cmd["step"]
                self._state.awaiting_approval = True
                self._state.approval_step     = step
                self._state.status            = "waiting for approval"
                self._state.current_target    = format_action_target(step, step.get("action", ""))
                if step.get("description"):
                    self._state.description   = step["description"]
                _refresh_ui()
                return

        def _poll_queue() -> None:
            try:
                while True:
                    cmd = self._cmd_queue.get_nowait()
                    if cmd.get("type") == "close":
                        _process_cmd(cmd)
                        return
                    _process_cmd(cmd)
            except queue.Empty:
                pass
            root.after(50, _poll_queue)

        root.after(100, _apply_click_through)
        root.after(50, _poll_queue)
        root.mainloop()
        self._running = False