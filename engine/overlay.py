"""
Tkinter floating overlay for Friday's live execution view.

Shows screenshot, model plan, step progress, completed-step log, and
risky-action approval. Runs on a background thread so the main loop is
never blocked. Mouse/keyboard events pass through on Windows except during
approval.
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

PANEL_W = 420
THUMB_H = 160
BASE_H = 500
MARGIN = 16

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


def update_screenshot(pil_image: Image.Image) -> None:
    """Show the latest captured screen thumbnail."""
    if _overlay is not None:
        _overlay.update_screenshot(pil_image)


def update_plan(message: str, steps: list) -> None:
    """Show the model's reasoning and imminent step batch."""
    if _overlay is not None:
        _overlay.update_plan(message, steps)


def update_strategy(
    plan_message: str,
    phases: list,
    current_phase_index: int = 0,
) -> None:
    """Show the high-level multi-phase plan."""
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
    """Push a step execution update to the overlay."""
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
    """Update only the status badge."""
    if _overlay is not None:
        _overlay.set_status(status)


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
    "halt": "#ef4444",
    "idle": "#6b7280",
}

STATUS_LABELS = {
    "running": "RUNNING",
    "waiting": "WAITING",
    "waiting for approval": "AWAITING APPROVAL",
    "complete": "COMPLETE",
    "error": "ERROR",
    "halt": "HALTED",
    "idle": "IDLE",
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
        text = step.get("text") or ""
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


def _format_phases(phases: list, current_phase_index: int, limit: int = 5) -> str:
    """Compact multi-line summary of high-level phases."""
    if not phases:
        return "No phases defined."

    lines: list[str] = []
    for i, phase in enumerate(phases[:limit]):
        title = phase.get("title") or phase.get("goal") or f"Phase {i + 1}"
        if i < current_phase_index:
            prefix = "✓"
        elif i == current_phase_index:
            prefix = "→"
        else:
            prefix = " "
        lines.append(f"{prefix} {i + 1}. {title}")

    if len(phases) > limit:
        lines.append(f"  … {len(phases) - limit} more phases")

    return "\n".join(lines)


def _format_upcoming_steps(plan_steps: list, step_index: int, limit: int = 4) -> str:
    """Compact multi-line summary of remaining plan steps."""
    if not plan_steps:
        return "No steps queued."

    remaining = plan_steps[step_index:] if step_index <= len(plan_steps) else []
    if not remaining:
        return "No steps queued."

    lines: list[str] = []
    for i, step in enumerate(remaining[:limit]):
        num = step_index + i + 1
        summary = format_action_target(step, step.get("action", ""))
        prefix = "→" if i == 0 else " "
        lines.append(f"{prefix} {num}. {summary}")

    if len(remaining) > limit:
        lines.append(f"  … and {len(remaining) - limit} more")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Controller
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
        self._cmd_queue.put(
            {"type": "plan", "message": message or "", "steps": steps or []}
        )

    def update_strategy(
        self,
        plan_message: str,
        phases: list,
        current_phase_index: int = 0,
    ) -> None:
        self._cmd_queue.put(
            {
                "type": "strategy",
                "plan_message": plan_message or "",
                "phases": phases or [],
                "current_phase_index": current_phase_index,
            }
        )

    def update(
        self,
        step_index: int,
        action: str,
        status: str,
        step: dict | None = None,
        task_name: str | None = None,
        iteration: int | None = None,
    ) -> None:
        self._cmd_queue.put(
            {
                "type": "update",
                "step_index": step_index,
                "action": action,
                "status": status,
                "step": step,
                "task_name": task_name,
                "iteration": iteration,
            }
        )

    def set_status(self, status: str) -> None:
        self._cmd_queue.put({"type": "set_status", "status": status})

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

        screen_w = root.winfo_screenwidth()

        def _position(height: int) -> None:
            root.geometry(
                f"{PANEL_W}x{height}+{screen_w - PANEL_W - MARGIN}+{MARGIN}"
            )

        _position(BASE_H)

        bg = "#1a1a2e"
        fg = "#e8e8f0"
        muted = "#8888aa"
        panel_bg = "#12121f"
        root.configure(bg=bg)

        title_font = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        body_font = tkfont.Font(family="Segoe UI", size=9)
        small_font = tkfont.Font(family="Segoe UI", size=8)
        mono_font = tkfont.Font(family="Consolas", size=9)
        badge_font = tkfont.Font(family="Segoe UI", size=8, weight="bold")

        task_lbl = tk.Label(root, text="", font=title_font, bg=bg, fg=fg, anchor="w")
        task_lbl.pack(fill="x", padx=12, pady=(10, 0))

        step_lbl = tk.Label(root, text="", font=body_font, bg=bg, fg=muted, anchor="w")
        step_lbl.pack(fill="x", padx=12, pady=(2, 6))

        thumb_frame = tk.Frame(root, bg=panel_bg, height=THUMB_H)
        thumb_frame.pack(fill="x", padx=12)
        thumb_frame.pack_propagate(False)

        thumb_lbl = tk.Label(
            thumb_frame,
            text="Waiting for screenshot…",
            font=body_font,
            bg=panel_bg,
            fg=muted,
        )
        thumb_lbl.pack(expand=True)

        badge_frame = tk.Frame(root, bg=bg)
        badge_frame.pack(fill="x", padx=12, pady=(8, 0))

        badge = tk.Label(
            badge_frame,
            text="IDLE",
            font=badge_font,
            bg=STATUS_COLORS["idle"],
            fg="#ffffff",
            padx=8,
            pady=2,
        )
        badge.pack(side="left")

        action_lbl = tk.Label(
            root, text="", font=mono_font, bg=bg, fg="#a8d8ff", anchor="w", wraplength=PANEL_W - 24
        )
        action_lbl.pack(fill="x", padx=12, pady=(6, 0))

        desc_lbl = tk.Label(
            root, text="", font=body_font, bg=bg, fg=fg, anchor="w", wraplength=PANEL_W - 24, justify="left"
        )
        desc_lbl.pack(fill="x", padx=12, pady=(2, 0))

        tk.Label(root, text="PLAN", font=small_font, bg=bg, fg=muted, anchor="w").pack(
            fill="x", padx=12, pady=(8, 0)
        )
        phases_lbl = tk.Label(
            root,
            text="No phases defined.",
            font=mono_font,
            bg=bg,
            fg="#c8a85a",
            anchor="nw",
            justify="left",
            wraplength=PANEL_W - 24,
        )
        phases_lbl.pack(fill="x", padx=12, pady=(0, 4))

        tk.Label(root, text="NEXT ACTIONS", font=small_font, bg=bg, fg=muted, anchor="w").pack(
            fill="x", padx=12, pady=(4, 0)
        )
        upcoming_lbl = tk.Label(
            root,
            text="No steps queued.",
            font=mono_font,
            bg=bg,
            fg="#c8a85a",
            anchor="nw",
            justify="left",
            wraplength=PANEL_W - 24,
        )
        upcoming_lbl.pack(fill="x", padx=12, pady=(0, 4))

        tk.Label(root, text="MODEL SAYS", font=small_font, bg=bg, fg=muted, anchor="w").pack(
            fill="x", padx=12, pady=(4, 0)
        )
        message_lbl = tk.Label(
            root, text="—", font=body_font, bg=bg, fg=fg, anchor="w", wraplength=PANEL_W - 24, justify="left"
        )
        message_lbl.pack(fill="x", padx=12, pady=(0, 4))

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
        log_toggle.pack(fill="x", padx=8, pady=(4, 0))

        log_frame = tk.Frame(root, bg=panel_bg)
        log_list = tk.Listbox(
            log_frame,
            font=mono_font,
            bg=panel_bg,
            fg="#88cc88",
            relief="flat",
            highlightthickness=0,
            selectbackground="#303060",
            height=4,
        )
        log_list.pack(fill="both", expand=True, padx=4, pady=4)

        approval_frame = tk.Frame(root, bg="#2a1a10", relief="flat")
        approval_lbl = tk.Label(
            approval_frame,
            text="",
            font=body_font,
            bg="#2a1a10",
            fg="#ffcc88",
            wraplength=PANEL_W - 24,
            justify="left",
        )
        approval_lbl.pack(fill="x", padx=10, pady=(8, 4))

        btn_row = tk.Frame(approval_frame, bg="#2a1a10")
        btn_row.pack(fill="x", padx=10, pady=(0, 8))

        def on_approve() -> None:
            self._set_approval_result(True)

        def on_reject() -> None:
            self._set_approval_result(False)

        tk.Button(
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
        ).pack(side="left", padx=(0, 8))

        tk.Button(
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
        ).pack(side="left")

        def _apply_click_through() -> None:
            if platform.system() != "Windows":
                return
            try:
                import ctypes

                hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
                gwl_exstyle = -20
                ws_ex_layered = 0x00080000
                ws_ex_transparent = 0x00000020
                ws_ex_topmost = 0x00000008
                style = ctypes.windll.user32.GetWindowLongW(hwnd, gwl_exstyle)
                ctypes.windll.user32.SetWindowLongW(
                    hwnd,
                    gwl_exstyle,
                    style | ws_ex_layered | ws_ex_transparent | ws_ex_topmost,
                )
            except Exception:
                pass

        def _disable_click_through() -> None:
            if platform.system() != "Windows":
                return
            try:
                import ctypes

                hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
                gwl_exstyle = -20
                ws_ex_layered = 0x00080000
                ws_ex_topmost = 0x00000008
                ws_ex_transparent = 0x00000020
                style = ctypes.windll.user32.GetWindowLongW(hwnd, gwl_exstyle)
                ctypes.windll.user32.SetWindowLongW(
                    hwnd,
                    gwl_exstyle,
                    (style | ws_ex_layered | ws_ex_topmost) & ~ws_ex_transparent,
                )
            except Exception:
                pass

        def _current_height() -> int:
            extra = 0
            if self._state.log_expanded:
                extra += 80
            if self._state.awaiting_approval:
                extra += 100
            return BASE_H + extra

        def _toggle_log() -> None:
            self._state.log_expanded = not self._state.log_expanded
            if self._state.log_expanded:
                log_toggle.config(text="▼ Completed steps")
                log_frame.pack(fill="both", expand=True, padx=8, pady=(2, 8))
            else:
                log_toggle.config(text="▶ Completed steps")
                log_frame.pack_forget()
            _position(_current_height())

        log_toggle.config(command=_toggle_log)

        def _refresh_thumb() -> None:
            pil = self._state.thumb_pil
            if pil is None:
                thumb_lbl.config(image="", text="Waiting for screenshot…")
                self._thumb_photo = None
                return
            self._thumb_photo = ImageTk.PhotoImage(pil)
            thumb_lbl.config(image=self._thumb_photo, text="")

        def _refresh_ui() -> None:
            s = self._state
            task_lbl.config(text=s.task_name or "Friday")

            if s.iteration > 0:
                if s.total_steps > 0:
                    step_lbl.config(
                        text=f"Iteration {s.iteration}  |  Step {s.step_index} of {s.total_steps}"
                    )
                else:
                    step_lbl.config(text=f"Iteration {s.iteration}")
            elif s.total_steps > 0:
                step_lbl.config(text=f"Step {s.step_index} of {s.total_steps}")
            else:
                step_lbl.config(text="")

            action_lbl.config(text=s.current_target or s.action.upper())
            desc_lbl.config(text=s.description or "")

            color = STATUS_COLORS.get(s.status, STATUS_COLORS["running"])
            label = STATUS_LABELS.get(s.status, s.status.upper())
            badge.config(text=label, bg=color)

            message_lbl.config(text=s.message or "—")
            phases_lbl.config(
                text=_format_phases(s.phases, s.current_phase_index)
            )
            upcoming_lbl.config(
                text=_format_upcoming_steps(s.plan_steps, s.step_index)
            )

            log_list.delete(0, "end")
            for entry in s.log_entries:
                log_list.insert("end", entry)

            _refresh_thumb()

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
                _disable_click_through()
            else:
                approval_frame.pack_forget()
                _apply_click_through()

            _position(_current_height())

        def _process_cmd(cmd: dict[str, Any]) -> None:
            cmd_type = cmd.get("type")

            if cmd_type == "close":
                root.quit()
                return

            if cmd_type == "screenshot":
                self._state.thumb_pil = cmd["image"]
                _refresh_ui()
                return

            if cmd_type == "plan":
                self._state.message = cmd["message"]
                self._state.plan_steps = cmd["steps"]
                self._state.step_index = 0
                _refresh_ui()
                return

            if cmd_type == "strategy":
                self._state.plan_message = cmd["plan_message"]
                self._state.phases = cmd["phases"]
                self._state.current_phase_index = cmd["current_phase_index"]
                _refresh_ui()
                return

            if cmd_type == "set_status":
                self._state.status = cmd["status"]
                _refresh_ui()
                return

            if cmd_type == "update":
                prev_index = self._state.step_index
                prev_action = self._state.action
                new_index = cmd["step_index"]
                new_action = cmd["action"]
                new_status = cmd["status"]
                step = cmd.get("step")

                if cmd.get("task_name") is not None:
                    self._state.task_name = cmd["task_name"]
                if cmd.get("iteration") is not None:
                    self._state.iteration = cmd["iteration"]
                if step and step.get("description"):
                    self._state.description = step["description"]

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
                if step.get("description"):
                    self._state.description = step["description"]
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
