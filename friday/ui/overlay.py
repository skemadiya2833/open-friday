"""
Tkinter floating overlay for Friday's live execution view.

Minimal panel: live screen, frame counter, task, reasoning stream, next steps.
Runs on a background thread; mouse/keyboard pass through on Windows except
during approval dialogs.
"""

from __future__ import annotations

import platform
import queue
import threading
from dataclasses import dataclass, field
from typing import Any

from PIL import Image, ImageTk

# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

PANEL_W = 380
THUMB_H = 150
REASONING_H = 110
BASE_H = 480
MARGIN = 16

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_overlay: "OverlayController | None" = None


def hide_for_capture() -> None:
    if _overlay is not None:
        _overlay.hide_for_capture()


def show_after_capture() -> None:
    if _overlay is not None:
        _overlay.show_after_capture()


def panel_bounds(screen_w: int, screen_h: int) -> tuple[int, int, int, int] | None:
    """Exact overlay rectangle in screen coords, or None if overlay is not running."""
    if _overlay is None or not _overlay.is_active:
        return None
    return _overlay.panel_bounds(screen_w, screen_h)


def set_live_mode(enabled: bool) -> None:
    if _overlay is not None:
        _overlay.set_live_mode(enabled)


def update_live_frame(pil_image: Image.Image, frame_index: int = 0) -> None:
    if _overlay is not None:
        _overlay.update_live_frame(pil_image, frame_index=frame_index)


def update_screenshot(pil_image: Image.Image) -> None:
    update_live_frame(pil_image)


def start(total_steps: int, task_name: str = "") -> None:
    global _overlay
    if _overlay is None:
        _overlay = OverlayController()
    _overlay.start(total_steps, task_name)


def update_plan(message: str, steps: list) -> None:
    if _overlay is not None:
        _overlay.update_plan(message, steps)


def update_strategy(
    plan_message: str,
    phases: list,
    current_phase_index: int = 0,
) -> None:
    """Kept for API compatibility — not shown in the simplified overlay."""
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
            step_index, action, status,
            step=step, task_name=task_name, iteration=iteration,
        )


def set_status(status: str) -> None:
    if _overlay is not None:
        _overlay.set_status(status)


def push_thinking(token: str) -> None:
    if _overlay is not None:
        _overlay.push_thinking(token)


def clear_thinking() -> None:
    if _overlay is not None:
        _overlay.clear_thinking()


def clear_perception() -> None:
    pass


def set_perception(scene: dict) -> None:
    pass


def set_thinking(text: str) -> None:
    if _overlay is not None:
        _overlay.set_thinking(text)


def sync_completed_steps(history: list[str]) -> None:
    pass


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
# Status labels (shown inline next to frame counter)
# ---------------------------------------------------------------------------

STATUS_COLORS = {
    "live":                 "#22c55e",
    "running":              "#3b82f6",
    "thinking":             "#8b5cf6",
    "aiming":               "#f59e0b",
    "verifying":            "#06b6d4",
    "waiting":              "#f59e0b",
    "waiting for approval": "#f59e0b",
    "complete":             "#22c55e",
    "error":                "#ef4444",
    "halt":                 "#ef4444",
    "idle":                 "#6b7280",
}

STATUS_LABELS = {
    "live":                 "LIVE",
    "running":              "RUNNING",
    "thinking":             "THINKING",
    "aiming":               "AIMING",
    "verifying":            "VERIFYING",
    "waiting":              "WAITING",
    "waiting for approval": "APPROVAL",
    "complete":             "DONE",
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
        return f"{act} ({x}, {y})" if x is not None and y is not None else act

    if act in ("TYPE", "PASTE", "SEARCH", "WIN_SEARCH"):
        text = step.get("text") or ""
        preview = text[:36] + ("…" if len(text) > 36 else "")
        return f'{act} "{preview}"'

    if act == "PRESS_KEY":
        return f"PRESS {step.get('key') or ''}"

    if act == "HOTKEY":
        keys = step.get("keys") or []
        return f"HOTKEY {'+'.join(keys)}"

    if act == "SAVE_FILE":
        name = step.get("text") or ""
        return f"SAVE {name}" if name else "SAVE"

    if act == "SCROLL":
        direction = step.get("direction", "down")
        return f"SCROLL {direction}"

    if act == "WAIT":
        return f"WAIT {step.get('duration', 1.5)}s"

    if act in ("DRAG", "DRAG_DROP"):
        return f"{act} → ({step.get('x2')},{step.get('y2')})"

    if act == "COMPLETE":
        return "COMPLETE"

    desc = (step.get("description") or "")[:50]
    return f"{act}: {desc}" if desc else act


def _format_next_steps(message: str, steps: list, limit: int = 5) -> str:
    lines: list[str] = []
    if message:
        lines.append(message.strip()[:180])
    if not steps:
        return "\n".join(lines) if lines else "Waiting for next action…"
    for i, step in enumerate(steps[:limit]):
        summary = format_action_target(step, step.get("action", ""))
        prefix = "→" if i == 0 else " "
        lines.append(f"{prefix} {summary}")
    if len(steps) > limit:
        lines.append(f"  +{len(steps) - limit} more")
    return "\n".join(lines)


def _frame_status_line(status: str, frame_index: int, live_mode: bool) -> str:
    label = STATUS_LABELS.get(status, status.upper())
    if live_mode and frame_index > 0:
        return f"{label}  ·  frame {frame_index}"
    if live_mode:
        return label
    return label


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

@dataclass
class OverlayState:
    task_name: str = ""
    status: str = "idle"
    message: str = ""
    plan_steps: list = field(default_factory=list)
    thumb_pil: Image.Image | None = None
    live_mode: bool = False
    live_frame_index: int = 0
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
        self._hide_event = threading.Event()
        self._show_event = threading.Event()
        self._approval_result: bool = False
        self._thread: threading.Thread | None = None
        self._running = False
        self._state = OverlayState()
        self._thumb_photo: ImageTk.PhotoImage | None = None
        self._hidden_for_capture = False
        self._hidden_lock = threading.Lock()
        self._panel_xy: tuple[int, int] = (0, 0)
        self._panel_size: tuple[int, int] = (PANEL_W, BASE_H)

    @property
    def is_active(self) -> bool:
        return self._running

    def panel_bounds(self, screen_w: int, screen_h: int) -> tuple[int, int, int, int]:
        """Return padded overlay bounds for vision masking."""
        x, y = self._panel_xy
        w, h = self._panel_size
        if w <= 0 or h <= 0:
            # Fallback before first layout pass
            x = max(0, screen_w - PANEL_W - MARGIN)
            y = MARGIN
            w, h = PANEL_W, BASE_H + 100
        pad = 12
        return (
            max(0, x - pad),
            max(0, y - pad),
            min(screen_w, x + w + pad),
            min(screen_h, y + h + pad),
        )

    def start(self, total_steps: int, task_name: str = "") -> None:
        self._state.task_name = task_name
        if not self._running:
            self._running = True
            self._thread = threading.Thread(target=self._run_ui, daemon=True)
            self._thread.start()

    def update_live_frame(self, pil_image: Image.Image, frame_index: int = 0) -> None:
        thumb = pil_image.copy()
        thumb.thumbnail((PANEL_W - 24, THUMB_H), Image.LANCZOS)
        self._cmd_queue.put({
            "type": "live_frame",
            "image": thumb,
            "frame_index": frame_index,
        })

    def set_live_mode(self, enabled: bool) -> None:
        self._cmd_queue.put({"type": "live_mode", "enabled": enabled})

    def update_plan(self, message: str, steps: list) -> None:
        self._cmd_queue.put({"type": "plan", "message": message or "", "steps": steps or []})

    def update_strategy(self, plan_message: str, phases: list, current_phase_index: int = 0) -> None:
        pass

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
            "status": status,
            "task_name": task_name,
        })

    def set_status(self, status: str) -> None:
        self._cmd_queue.put({"type": "set_status", "status": status})

    def push_thinking(self, token: str) -> None:
        self._cmd_queue.put({"type": "thinking_token", "token": token})

    def clear_thinking(self) -> None:
        self._cmd_queue.put({"type": "thinking_clear"})

    def set_thinking(self, text: str) -> None:
        self._cmd_queue.put({"type": "thinking_set", "text": text or ""})

    def hide_for_capture(self) -> None:
        with self._hidden_lock:
            if not self._running or self._hidden_for_capture:
                return
        self._hide_event.clear()
        self._cmd_queue.put({"type": "hide_capture"})
        if not self._hide_event.wait(timeout=1.0):
            print("[Overlay] hide_for_capture timed out — capture may include UI.")

    def show_after_capture(self) -> None:
        with self._hidden_lock:
            if not self._running or not self._hidden_for_capture:
                return
        self._show_event.clear()
        self._cmd_queue.put({"type": "show_capture"})
        self._show_event.wait(timeout=1.0)

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

    def _run_ui(self) -> None:
        import tkinter as tk
        from tkinter import font as tkfont

        root = tk.Tk()
        root.title("Friday")
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.attributes("-alpha", 0.94)

        screen_w = root.winfo_screenwidth()

        def _position(height: int) -> None:
            x = screen_w - PANEL_W - MARGIN
            y = MARGIN
            root.geometry(f"{PANEL_W}x{height}+{x}+{y}")
            self._panel_xy = (x, y)
            self._panel_size = (PANEL_W, height)

        _position(BASE_H)

        bg = "#0d0d14"
        fg = "#e8e8f0"
        muted = "#6b6b8a"
        panel_bg = "#12121c"
        think_bg = "#0a0a12"
        accent = "#a78bfa"

        root.configure(bg=bg)

        hdr_font = tkfont.Font(family="Segoe UI", size=8, weight="bold")
        task_font = tkfont.Font(family="Segoe UI", size=10)
        body_font = tkfont.Font(family="Segoe UI", size=9)
        mono_font = tkfont.Font(family="Consolas", size=9)
        status_font = tkfont.Font(family="Consolas", size=8)

        def _section(title: str) -> tk.Label:
            return tk.Label(root, text=title, font=hdr_font, bg=bg, fg=muted, anchor="w")

        # -- Screen ----------------------------------------------------------
        screen_hdr = tk.Frame(root, bg=bg)
        screen_hdr.pack(fill="x", padx=12, pady=(10, 2))
        tk.Label(screen_hdr, text="SCREEN", font=hdr_font, bg=bg, fg=muted, anchor="w").pack(
            side="left",
        )
        frame_lbl = tk.Label(
            screen_hdr, text="IDLE", font=status_font, bg=bg, fg="#22c55e", anchor="e",
        )
        frame_lbl.pack(side="right")

        thumb_frame = tk.Frame(root, bg=panel_bg, height=THUMB_H)
        thumb_frame.pack(fill="x", padx=12)
        thumb_frame.pack_propagate(False)

        thumb_lbl = tk.Label(
            thumb_frame, text="Starting…", font=body_font, bg=panel_bg, fg=muted,
        )
        thumb_lbl.pack(expand=True)

        # -- Task ------------------------------------------------------------
        _section("TASK").pack(fill="x", padx=12, pady=(10, 2))
        task_lbl = tk.Label(
            root, text="", font=task_font, bg=bg, fg=fg,
            anchor="nw", justify="left", wraplength=PANEL_W - 24,
        )
        task_lbl.pack(fill="x", padx=12)

        # -- Reasoning -------------------------------------------------------
        _section("REASONING").pack(fill="x", padx=12, pady=(10, 2))
        think_frame = tk.Frame(root, bg=think_bg, height=REASONING_H)
        think_frame.pack(fill="x", padx=12)
        think_frame.pack_propagate(False)

        think_text = tk.Text(
            think_frame,
            font=body_font,
            bg=think_bg,
            fg=accent,
            relief="flat",
            highlightthickness=0,
            wrap="word",
            state="disabled",
            cursor="arrow",
        )
        think_text.pack(fill="both", expand=True, padx=6, pady=6)

        # -- Next steps ------------------------------------------------------
        _section("NEXT STEPS").pack(fill="x", padx=12, pady=(10, 2))
        steps_lbl = tk.Label(
            root, text="Waiting for next action…", font=mono_font,
            bg=bg, fg="#c8a85a", anchor="nw", justify="left",
            wraplength=PANEL_W - 24,
        )
        steps_lbl.pack(fill="x", padx=12, pady=(0, 10))

        # -- Approval (hidden unless needed) ---------------------------------
        approval_frame = tk.Frame(root, bg="#2a1a10")
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
            bg="#166534", fg="#ffffff", relief="flat", padx=12, pady=4,
            command=lambda: self._set_approval_result(True),
        ).pack(side="left", padx=(0, 8))
        tk.Button(
            btn_row, text="Reject", font=body_font,
            bg="#7f1d1d", fg="#ffffff", relief="flat", padx=12, pady=4,
            command=lambda: self._set_approval_result(False),
        ).pack(side="left")

        def _apply_click_through() -> None:
            if platform.system() != "Windows":
                return
            try:
                import ctypes
                hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
                GWL_EXSTYLE = -20
                WS_EX_LAYERED = 0x00080000
                WS_EX_TRANSPARENT = 0x00000020
                WS_EX_TOPMOST = 0x00000008
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
                GWL_EXSTYLE = -20
                WS_EX_LAYERED = 0x00080000
                WS_EX_TOPMOST = 0x00000008
                WS_EX_TRANSPARENT = 0x00000020
                style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                ctypes.windll.user32.SetWindowLongW(
                    hwnd, GWL_EXSTYLE,
                    (style | WS_EX_LAYERED | WS_EX_TOPMOST) & ~WS_EX_TRANSPARENT,
                )
            except Exception:
                pass

        def _panel_height() -> int:
            return BASE_H + (100 if self._state.awaiting_approval else 0)

        def _refresh_thumb() -> None:
            pil = self._state.thumb_pil
            if pil is None:
                thumb_lbl.config(image="", text="Starting…")
                self._thumb_photo = None
                return
            self._thumb_photo = ImageTk.PhotoImage(pil)
            thumb_lbl.config(image=self._thumb_photo, text="")

        def _append_thinking(text: str) -> None:
            think_text.config(state="normal")
            think_text.insert("end", text)
            content = think_text.get("1.0", "end")
            if len(content) > 800:
                think_text.delete("1.0", f"1.{len(content) - 650}")
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

        def _refresh_ui() -> None:
            s = self._state
            task_lbl.config(text=s.task_name or "Friday")
            steps_lbl.config(text=_format_next_steps(s.message, s.plan_steps))

            status_text = _frame_status_line(s.status, s.live_frame_index, s.live_mode)
            status_color = STATUS_COLORS.get(s.status, STATUS_COLORS["idle"])
            frame_lbl.config(text=status_text, fg=status_color)

            _refresh_thumb()

            if s.awaiting_approval:
                step = s.approval_step or {}
                summary = format_action_target(step, step.get("action", ""))
                approval_lbl.config(
                    text=f"Approve risky action?\n{summary}"
                )
                approval_frame.pack(fill="x", padx=8, pady=(0, 8))
                _disable_click_through()
            else:
                approval_frame.pack_forget()
                _apply_click_through()

            _position(_panel_height())

        def _process_cmd(cmd: dict[str, Any]) -> None:
            t = cmd.get("type")

            if t == "close":
                root.quit()
                return

            if t == "live_frame":
                self._state.thumb_pil = cmd["image"]
                self._state.live_frame_index = cmd.get("frame_index", 0)
                _refresh_thumb()
                status_text = _frame_status_line(
                    self._state.status,
                    self._state.live_frame_index,
                    self._state.live_mode,
                )
                status_color = STATUS_COLORS.get(self._state.status, STATUS_COLORS["idle"])
                frame_lbl.config(text=status_text, fg=status_color)
                return

            if t == "live_mode":
                self._state.live_mode = bool(cmd.get("enabled"))
                if self._state.live_mode:
                    self._state.status = "live"
                _refresh_ui()
                return

            if t == "plan":
                self._state.message = cmd["message"]
                self._state.plan_steps = cmd["steps"]
                _refresh_ui()
                return

            if t == "set_status":
                self._state.status = cmd["status"]
                status_text = _frame_status_line(
                    self._state.status,
                    self._state.live_frame_index,
                    self._state.live_mode,
                )
                status_color = STATUS_COLORS.get(self._state.status, STATUS_COLORS["idle"])
                frame_lbl.config(text=status_text, fg=status_color)
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

            if t == "hide_capture":
                root.withdraw()
                root.update_idletasks()
                with self._hidden_lock:
                    self._hidden_for_capture = True
                self._hide_event.set()
                return

            if t == "show_capture":
                root.deiconify()
                root.update_idletasks()
                with self._hidden_lock:
                    self._hidden_for_capture = False
                if not self._state.awaiting_approval:
                    _apply_click_through()
                self._show_event.set()
                return

            if t == "update":
                if cmd.get("task_name"):
                    self._state.task_name = cmd["task_name"]
                if cmd.get("status"):
                    self._state.status = cmd["status"]
                self._state.awaiting_approval = False
                _refresh_ui()
                return

            if t == "approval":
                step = cmd["step"]
                self._state.awaiting_approval = True
                self._state.approval_step = step
                self._state.status = "waiting for approval"
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
