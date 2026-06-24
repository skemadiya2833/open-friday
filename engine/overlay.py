"""
Tkinter floating overlay for live step progress.

Runs on a background thread so the main execution loop is never blocked
by tkinter's mainloop. Mouse/keyboard events pass through on Windows.
"""

from __future__ import annotations

import platform
import queue
import threading
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_overlay: "OverlayController | None" = None


def start(total_steps: int, task_name: str = "") -> None:
    """Launch the overlay window (no-op if already running)."""
    global _overlay
    if _overlay is None:
        _overlay = OverlayController()
    _overlay.start(total_steps, task_name)


def update(
    step_index: int,
    action: str,
    status: str,
    step: dict | None = None,
    task_name: str | None = None,
) -> None:
    """Push a state update to the overlay."""
    if _overlay is not None:
        _overlay.update(step_index, action, status, step=step, task_name=task_name)


def await_approval(step: dict) -> bool:
    """Block until the operator approves or rejects in the overlay."""
    if _overlay is None:
        return False
    return _overlay.await_approval(step)


def close() -> None:
    """Tear down the overlay window."""
    global _overlay
    if _overlay is not None:
        _overlay.close()
        _overlay = None


# ---------------------------------------------------------------------------
# Status colours
# ---------------------------------------------------------------------------

STATUS_COLORS = {
    "running": "#3b82f6",
    "waiting": "#f59e0b",
    "waiting for approval": "#f59e0b",
    "complete": "#22c55e",
    "error": "#ef4444",
}

STATUS_LABELS = {
    "running": "RUNNING",
    "waiting": "AWAITING APPROVAL",
    "waiting for approval": "AWAITING APPROVAL",
    "complete": "COMPLETE",
    "error": "ERROR",
}


def format_action_target(step: dict | None, action: str = "") -> str:
    """Human-readable summary of the current action and its target."""
    if not step:
        return action.upper() if action else ""

    act = (step.get("action") or action or "").upper()

    if act in ("CLICK", "HOVER"):
        x, y = step.get("x"), step.get("y")
        return f"{act} at ({x}, {y})" if x is not None and y is not None else act

    if act in ("TYPE", "PASTE", "SEARCH", "WIN_SEARCH"):
        text = step.get("text") or ""          # guard: None -> ""
        preview = text[:40] + ("..." if len(text) > 40 else "")
        return f'{act} "{preview}"'

    if act == "PRESS_KEY":
        key = step.get("key") or ""
        return f"PRESS_KEY {key}"

    if act == "SAVE_FILE":
        return "SAVE_FILE (Ctrl+S)"

    if act == "SCROLL":
        direction = step.get("direction", "down")
        x, y = step.get("x"), step.get("y")
        if x and y:
            return f"SCROLL {direction} at ({x}, {y})"
        return f"SCROLL {direction}"

    if act == "WAIT":
        return f"WAIT {step.get('duration', 1.5)}s"

    if act == "DRAG":
        return (
            f"DRAG ({step.get('x')},{step.get('y')})"
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


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------

@dataclass
class OverlayState:
    task_name: str = ""
    total_steps: int = 0
    step_index: int = 0
    action: str = ""
    status: str = "running"
    current_target: str = ""
    log_entries: list[str] = field(default_factory=list)
    log_expanded: bool = False
    awaiting_approval: bool = False
    approval_step: dict | None = None


class OverlayController:
    def __init__(self) -> None:
        self._cmd_queue: queue.Queue = queue.Queue()
        self._approval_event = threading.Event()
        self._approval_result: bool = False
        self._thread: threading.Thread | None = None
        self._running = False
        self._state = OverlayState()

    def start(self, total_steps: int, task_name: str = "") -> None:
        self._state.task_name = task_name
        self._state.total_steps = total_steps
        if not self._running:
            self._running = True
            self._thread = threading.Thread(target=self._run_ui, daemon=True)
            self._thread.start()

    def update(
        self,
        step_index: int,
        action: str,
        status: str,
        step: dict | None = None,
        task_name: str | None = None,
    ) -> None:
        if task_name is not None:
            self._state.task_name = task_name
        self._cmd_queue.put(
            {
                "type": "update",
                "step_index": step_index,
                "action": action,
                "status": status,
                "step": step,
            }
        )

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

    # -- UI thread ------------------------------------------------------------

    def _run_ui(self) -> None:
        import tkinter as tk
        from tkinter import font as tkfont

        root = tk.Tk()
        root.title("Friday")
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.attributes("-alpha", 0.92)

        # Position top-right of primary monitor
        panel_w, panel_h = 360, 220
        screen_w = root.winfo_screenwidth()
        root.geometry(f"{panel_w}x{panel_h}+{screen_w - panel_w - 16}+16")

        bg = "#1a1a2e"
        fg = "#e8e8f0"
        muted = "#8888aa"
        root.configure(bg=bg)

        title_font = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        body_font = tkfont.Font(family="Segoe UI", size=9)
        mono_font = tkfont.Font(family="Consolas", size=9)
        badge_font = tkfont.Font(family="Segoe UI", size=8, weight="bold")

        # --- widgets ---
        task_lbl = tk.Label(root, text="", font=title_font, bg=bg, fg=fg, anchor="w")
        task_lbl.pack(fill="x", padx=12, pady=(10, 2))

        step_lbl = tk.Label(root, text="", font=body_font, bg=bg, fg=muted, anchor="w")
        step_lbl.pack(fill="x", padx=12)

        action_lbl = tk.Label(root, text="", font=mono_font, bg=bg, fg="#a8d8ff", anchor="w")
        action_lbl.pack(fill="x", padx=12, pady=(4, 0))

        badge_frame = tk.Frame(root, bg=bg)
        badge_frame.pack(fill="x", padx=12, pady=(6, 0))

        badge = tk.Label(
            badge_frame,
            text="RUNNING",
            font=badge_font,
            bg=STATUS_COLORS["running"],
            fg="#ffffff",
            padx=8,
            pady=2,
        )
        badge.pack(side="left")

        # Collapsible log
        log_toggle = tk.Button(
            root,
            text="▶ Completed steps",
            font=body_font,
            bg="#252540",
            fg=muted,
            relief="flat",
            activebackground="#303060",
            activeforeground=fg,
            anchor="w",
            padx=8,
            command=lambda: None,
        )
        log_toggle.pack(fill="x", padx=8, pady=(8, 0))

        log_frame = tk.Frame(root, bg="#12121f")
        log_list = tk.Listbox(
            log_frame,
            font=mono_font,
            bg="#12121f",
            fg="#88cc88",
            relief="flat",
            highlightthickness=0,
            selectbackground="#303060",
            height=4,
        )
        log_list.pack(fill="both", expand=True, padx=4, pady=4)

        # Approval panel (hidden by default)
        approval_frame = tk.Frame(root, bg="#2a1a10", relief="flat")
        approval_lbl = tk.Label(
            approval_frame,
            text="",
            font=body_font,
            bg="#2a1a10",
            fg="#ffcc88",
            wraplength=panel_w - 24,
            justify="left",
        )
        approval_lbl.pack(fill="x", padx=10, pady=(8, 4))

        btn_row = tk.Frame(approval_frame, bg="#2a1a10")
        btn_row.pack(fill="x", padx=10, pady=(0, 8))

        def on_approve() -> None:
            self._set_approval_result(True)

        def on_reject() -> None:
            self._set_approval_result(False)

        approve_btn = tk.Button(
            btn_row,
            text="Approve",
            font=body_font,
            bg="#166534",
            fg="#ffffff",
            relief="flat",
            activebackground="#15803d",
            padx=12,
            pady=4,
            command=on_approve,
        )
        approve_btn.pack(side="left", padx=(0, 8))

        reject_btn = tk.Button(
            btn_row,
            text="Reject",
            font=body_font,
            bg="#7f1d1d",
            fg="#ffffff",
            relief="flat",
            activebackground="#991b1b",
            padx=12,
            pady=4,
            command=on_reject,
        )
        reject_btn.pack(side="left")

        # --- click-through on Windows -----------------------------------------
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
                    hwnd,
                    GWL_EXSTYLE,
                    style | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOPMOST,
                )
            except Exception:
                pass

        # --- state refresh ----------------------------------------------------
        def _toggle_log() -> None:
            self._state.log_expanded = not self._state.log_expanded
            if self._state.log_expanded:
                log_toggle.config(text="▼ Completed steps")
                log_frame.pack(fill="both", expand=True, padx=8, pady=(2, 8))
                root.geometry(f"{panel_w}x{panel_h + 80}+{screen_w - panel_w - 16}+16")
            else:
                log_toggle.config(text="▶ Completed steps")
                log_frame.pack_forget()
                root.geometry(f"{panel_w}x{panel_h}+{screen_w - panel_w - 16}+16")

        log_toggle.config(command=_toggle_log)

        def _refresh_ui() -> None:
            s = self._state
            task_lbl.config(text=s.task_name or "Friday")
            if s.total_steps > 0:
                step_lbl.config(text=f"Step {s.step_index} of {s.total_steps}")
            else:
                step_lbl.config(text=f"Step {s.step_index}")

            action_lbl.config(text=s.current_target or s.action.upper())
            color = STATUS_COLORS.get(s.status, STATUS_COLORS["running"])
            label = STATUS_LABELS.get(s.status, s.status.upper())
            badge.config(text=label, bg=color)

            log_list.delete(0, "end")
            for entry in s.log_entries:
                log_list.insert("end", entry)

            if s.awaiting_approval:
                step = s.approval_step or {}
                summary = format_action_target(step, step.get("action", ""))
                approval_lbl.config(
                    text=(
                        f"Risky action requires approval:\n"
                        f"{summary}\n"
                        f"{step.get('description', '')}"
                    )
                )
                approval_frame.pack(fill="x", padx=8, pady=(6, 8))
                root.geometry(f"{panel_w}x{panel_h + 100}+{screen_w - panel_w - 16}+16")
                # Approval buttons must receive clicks — disable click-through
                if platform.system() == "Windows":
                    try:
                        import ctypes

                        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
                        GWL_EXSTYLE = -20
                        WS_EX_LAYERED = 0x00080000
                        WS_EX_TOPMOST = 0x00000008
                        style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                        ctypes.windll.user32.SetWindowLongW(
                            hwnd,
                            GWL_EXSTYLE,
                            (style | WS_EX_LAYERED | WS_EX_TOPMOST) & ~0x00000020,
                        )
                    except Exception:
                        pass
            else:
                approval_frame.pack_forget()
                if not s.log_expanded:
                    root.geometry(f"{panel_w}x{panel_h}+{screen_w - panel_w - 16}+16")
                _apply_click_through()

        def _process_cmd(cmd: dict[str, Any]) -> None:
            cmd_type = cmd.get("type")

            if cmd_type == "close":
                root.quit()
                return

            if cmd_type == "update":
                prev_index = self._state.step_index
                prev_action = self._state.action
                new_index = cmd["step_index"]
                new_action = cmd["action"]
                new_status = cmd["status"]
                step = cmd.get("step")

                # Log completed step when advancing
                if (
                    new_status == "complete"
                    and prev_index > 0
                    and prev_index == new_index
                ):
                    entry = f"✓ {prev_index}. {format_action_target(step, prev_action)}"
                    if entry not in self._state.log_entries:
                        self._state.log_entries.append(entry)
                elif new_status == "complete" and step:
                    entry = f"✓ {new_index}. {format_action_target(step, new_action)}"
                    if entry not in self._state.log_entries:
                        self._state.log_entries.append(entry)

                self._state.step_index = new_index
                self._state.action = new_action
                self._state.status = new_status
                if step:
                    self._state.current_target = format_action_target(step, new_action)
                self._state.awaiting_approval = False
                _refresh_ui()

            elif cmd_type == "approval":
                step = cmd["step"]
                self._state.awaiting_approval = True
                self._state.approval_step = step
                self._state.status = "waiting for approval"
                self._state.current_target = format_action_target(
                    step, step.get("action", "")
                )
                _refresh_ui()

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
            root.after(80, _poll_queue)

        root.after(100, _apply_click_through)
        root.after(80, _poll_queue)
        root.mainloop()
        self._running = False