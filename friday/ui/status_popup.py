"""
Compact always-on-top status popup shown while the agent runs.

Displays task, status, thinking stream, and current action. Includes
Pause / Stop and approval controls so the operator can stay hands-on
while the main control center is hidden.
"""

from __future__ import annotations

import platform
import tkinter as tk
from tkinter import font as tkfont
from typing import Callable

from friday.ui.mask import register_region, unregister_region

# Match FridayApp theme
C = {
    "bg": "#0c1014",
    "panel": "#121820",
    "line": "#1e2a36",
    "fg": "#e6edf3",
    "muted": "#7d8b99",
    "dim": "#4a5866",
    "brand": "#3dd6c6",
    "accent": "#f0b429",
    "think": "#9bb8ff",
    "ok": "#3ecf8e",
    "warn": "#f0b429",
    "bad": "#f07178",
    "btn": "#1a2733",
    "btn_go": "#0d3d38",
    "btn_stop": "#3d1518",
    "btn_pause": "#3d3010",
}

STATUS_COLOR = {
    "idle": C["muted"],
    "live": C["ok"],
    "running": C["brand"],
    "thinking": C["think"],
    "aiming": C["warn"],
    "verifying": C["think"],
    "paused": C["warn"],
    "waiting for approval": C["warn"],
    "complete": C["ok"],
    "error": C["bad"],
    "halt": C["bad"],
}

PANEL_W = 340
PANEL_H = 420
MARGIN = 16
MASK_NAME = "friday_status_popup"


def _action_label(step: dict | None) -> str:
    if not step:
        return "—"
    act = str(step.get("action") or "").upper()
    if act in ("CLICK", "DOUBLE_CLICK", "RIGHT_CLICK", "HOVER", "MIDDLE_CLICK"):
        return f"{act}  ({step.get('x')}, {step.get('y')})"
    if act in ("TYPE", "PASTE", "WIN_SEARCH", "SEARCH", "KNOWLEDGE_SEARCH"):
        text = step.get("text") or step.get("query") or ""
        preview = text[:36] + ("…" if len(text) > 36 else "")
        return f'{act}  "{preview}"'
    if act == "NAVIGATE":
        return f"NAVIGATE  {step.get('url') or step.get('text') or ''}"
    if act == "HOTKEY":
        keys = step.get("keys") or []
        return f"HOTKEY  {'+'.join(keys)}"
    if act == "PRESS_KEY":
        return f"PRESS  {step.get('key') or ''}"
    if act == "SCROLL":
        return f"SCROLL  {step.get('direction', 'down')}"
    if act == "WAIT":
        return f"WAIT  {step.get('duration', 1)}s"
    desc = (step.get("description") or "")[:40]
    return f"{act}: {desc}" if desc else act


def _force_show_win32(widget: tk.Misc) -> None:
    """Keep popup visible even when the parent Tk window is minimized."""
    try:
        import ctypes
        user32 = ctypes.windll.user32
        # Tk winfo_id is the inner HWND; GetParent yields the real window
        hwnd = user32.GetParent(int(widget.winfo_id()))
        if not hwnd:
            hwnd = int(widget.winfo_id())
        SW_SHOWNOACTIVATE = 4
        HWND_TOPMOST = -1
        SWP_NOMOVE = 0x0002
        SWP_NOSIZE = 0x0001
        SWP_SHOWWINDOW = 0x0040
        SWP_NOACTIVATE = 0x0010
        user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
        user32.SetWindowPos(
            hwnd, HWND_TOPMOST, 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW | SWP_NOACTIVATE,
        )
    except Exception:
        pass


class StatusPopup:
    """Small floating panel for live agent progress."""

    def __init__(
        self,
        master: tk.Tk,
        *,
        on_pause: Callable[[], None] | None = None,
        on_stop: Callable[[], None] | None = None,
        on_approve: Callable[[bool], None] | None = None,
        on_restore: Callable[[], None] | None = None,
    ) -> None:
        self._on_pause = on_pause
        self._on_stop = on_stop
        self._on_approve = on_approve
        self._on_restore = on_restore
        self._paused = False
        self._iteration = 0
        self._mask_job: str | None = None

        self.win = tk.Toplevel(master)
        self.win.title("Friday")
        self.win.configure(bg=C["bg"])
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        try:
            self.win.attributes("-alpha", 0.96)
        except tk.TclError:
            pass

        self._fonts = self._build_fonts()
        self._build()
        self._place()
        self.win.bind("<Configure>", lambda _e: self._schedule_mask_update())
        self.win.after(100, self._update_mask_region)

    def _build_fonts(self) -> dict[str, tkfont.Font]:
        mono = "Cascadia Mono"
        try:
            probe = tkfont.Font(family=mono, size=9)
            if "cascadia" not in probe.actual("family").lower():
                mono = "Consolas"
        except tk.TclError:
            mono = "Consolas"
        return {
            "brand": tkfont.Font(family="Segoe UI Semibold", size=11),
            "title": tkfont.Font(family="Segoe UI Semibold", size=10),
            "body": tkfont.Font(family="Segoe UI", size=9),
            "mono": tkfont.Font(family=mono, size=9),
            "status": tkfont.Font(family=mono, size=9, weight="bold"),
        }

    def _build(self) -> None:
        f = self._fonts
        root = self.win
        pad = tk.Frame(root, bg=C["bg"], padx=12, pady=10)
        pad.pack(fill="both", expand=True)

        # Header
        hdr = tk.Frame(pad, bg=C["bg"])
        hdr.pack(fill="x")
        tk.Label(
            hdr, text="FRIDAY", font=f["brand"], bg=C["bg"], fg=C["brand"],
        ).pack(side="left")
        self.tick_lbl = tk.Label(
            hdr, text="tick 0", font=f["mono"], bg=C["bg"], fg=C["dim"],
        )
        self.tick_lbl.pack(side="right")

        status_row = tk.Frame(pad, bg=C["bg"])
        status_row.pack(fill="x", pady=(6, 0))
        self.status_dot = tk.Label(
            status_row, text="●", font=f["status"], bg=C["bg"], fg=C["muted"],
        )
        self.status_dot.pack(side="left")
        self.status_lbl = tk.Label(
            status_row, text="RUNNING", font=f["status"],
            bg=C["bg"], fg=C["muted"],
        )
        self.status_lbl.pack(side="left", padx=(4, 0))

        tk.Frame(pad, bg=C["line"], height=1).pack(fill="x", pady=(8, 8))

        # Task
        tk.Label(
            pad, text="TASK", font=f["title"], bg=C["bg"], fg=C["muted"],
            anchor="w",
        ).pack(fill="x")
        self.task_lbl = tk.Label(
            pad, text="", font=f["body"], bg=C["panel"], fg=C["fg"],
            anchor="nw", justify="left", wraplength=PANEL_W - 40,
            padx=8, pady=6,
        )
        self.task_lbl.pack(fill="x", pady=(4, 0))

        # Action
        tk.Label(
            pad, text="DOING", font=f["title"], bg=C["bg"], fg=C["muted"],
            anchor="w",
        ).pack(fill="x", pady=(10, 0))
        self.action_lbl = tk.Label(
            pad, text="—", font=f["mono"], bg=C["panel"], fg=C["accent"],
            anchor="nw", justify="left", wraplength=PANEL_W - 40,
            padx=8, pady=6,
        )
        self.action_lbl.pack(fill="x", pady=(4, 0))

        # Thinking
        tk.Label(
            pad, text="THINKING", font=f["title"], bg=C["bg"], fg=C["muted"],
            anchor="w",
        ).pack(fill="x", pady=(10, 0))
        think_frame = tk.Frame(pad, bg=C["panel"], height=140)
        think_frame.pack(fill="both", expand=True, pady=(4, 0))
        think_frame.pack_propagate(False)
        self.think_text = tk.Text(
            think_frame, font=f["body"], bg=C["panel"], fg=C["think"],
            relief="flat", highlightthickness=0, wrap="word",
            state="disabled", padx=6, pady=6,
        )
        self.think_text.pack(fill="both", expand=True)

        # Approval (hidden by default)
        self.approval_frame = tk.Frame(pad, bg="#2a1f10")
        self.approval_lbl = tk.Label(
            self.approval_frame, text="", font=f["body"],
            bg="#2a1f10", fg=C["warn"], wraplength=PANEL_W - 48,
            justify="left", padx=8, pady=6,
        )
        self.approval_lbl.pack(fill="x")
        appr_row = tk.Frame(self.approval_frame, bg="#2a1f10")
        appr_row.pack(fill="x", padx=8, pady=(0, 8))
        self._btn(appr_row, "Approve", "#14532d", C["ok"], lambda: self._approve(True)).pack(
            side="left", padx=(0, 6),
        )
        self._btn(appr_row, "Reject", "#7f1d1d", C["bad"], lambda: self._approve(False)).pack(
            side="left",
        )

        # Controls
        ctrl = tk.Frame(pad, bg=C["bg"])
        ctrl.pack(fill="x", pady=(10, 0))
        self.pause_btn = self._btn(ctrl, "Pause", C["btn_pause"], C["warn"], self._pause)
        self.pause_btn.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.stop_btn = self._btn(ctrl, "Stop", C["btn_stop"], C["bad"], self._stop)
        self.stop_btn.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self._btn(ctrl, "Show", C["btn"], C["brand"], self._restore).pack(
            side="left", fill="x", expand=True,
        )

    def _btn(self, parent: tk.Widget, text: str, bg: str, fg: str, command) -> tk.Button:
        return tk.Button(
            parent, text=text, font=self._fonts["body"],
            bg=bg, fg=fg, activebackground=bg, activeforeground=fg,
            relief="flat", padx=8, pady=5, cursor="hand2",
            command=command,
        )

    def _place(self) -> None:
        self.win.update_idletasks()
        sw = self.win.winfo_screenwidth()
        x = max(0, sw - PANEL_W - MARGIN)
        y = MARGIN
        self.win.geometry(f"{PANEL_W}x{PANEL_H}+{x}+{y}")

    # ------------------------------------------------------------------
    # Public updates
    # ------------------------------------------------------------------

    def force_visible(self) -> None:
        """Re-show after parent minimize/withdraw (Windows hides child Toplevels)."""
        try:
            self.win.deiconify()
            self.win.lift()
            self.win.attributes("-topmost", True)
            self.win.update_idletasks()
            if platform.system() == "Windows":
                _force_show_win32(self.win)
        except tk.TclError:
            pass

    def set_task(self, text: str) -> None:
        preview = text.strip()
        if len(preview) > 160:
            preview = preview[:157] + "…"
        self.task_lbl.config(text=preview or "—")

    def set_status(self, status: str) -> None:
        color = STATUS_COLOR.get(status, C["muted"])
        self.status_dot.config(fg=color)
        self.status_lbl.config(text=status.upper(), fg=color)

    def set_tick(self, iteration: int) -> None:
        self._iteration = iteration
        self.tick_lbl.config(text=f"tick {iteration}")

    def set_action(self, step: dict | None, message: str = "") -> None:
        label = _action_label(step)
        if message:
            label = f"{label}\n{message}"
        self.action_lbl.config(text=label)

    def set_thinking(self, text: str) -> None:
        self.think_text.config(state="normal")
        self.think_text.delete("1.0", "end")
        if text:
            self.think_text.insert("1.0", text)
        self.think_text.config(state="disabled")

    def append_thinking(self, token: str) -> None:
        self.think_text.config(state="normal")
        self.think_text.insert("end", token)
        content = self.think_text.get("1.0", "end")
        if len(content) > 1800:
            self.think_text.delete("1.0", f"1.{len(content) - 1400}")
        self.think_text.see("end")
        self.think_text.config(state="disabled")

    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        self.pause_btn.config(text="Resume" if paused else "Pause")

    def show_approval(self, step: dict) -> None:
        summary = _action_label(step)
        desc = step.get("description") or ""
        text = f"Approval required\n{summary}"
        if desc:
            text += f"\n{desc}"
        self.approval_lbl.config(text=text)
        if not self.approval_frame.winfo_ismapped():
            self.approval_frame.pack(fill="x", pady=(8, 0), before=self.pause_btn.master)
        self.set_status("waiting for approval")

    def hide_approval(self) -> None:
        if self.approval_frame.winfo_ismapped():
            self.approval_frame.pack_forget()

    def destroy(self) -> None:
        unregister_region(MASK_NAME)
        try:
            self.win.destroy()
        except tk.TclError:
            pass

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def _pause(self) -> None:
        if self._on_pause:
            self._on_pause()

    def _stop(self) -> None:
        if self._on_stop:
            self._on_stop()

    def _approve(self, approved: bool) -> None:
        if self._on_approve:
            self._on_approve(approved)
        self.hide_approval()

    def _restore(self) -> None:
        if self._on_restore:
            self._on_restore()

    # ------------------------------------------------------------------
    # Vision mask
    # ------------------------------------------------------------------

    def _schedule_mask_update(self) -> None:
        if self._mask_job is not None:
            try:
                self.win.after_cancel(self._mask_job)
            except tk.TclError:
                pass
        self._mask_job = self.win.after(150, self._update_mask_region)

    def _update_mask_region(self) -> None:
        try:
            self.win.update_idletasks()
            x = self.win.winfo_rootx()
            y = self.win.winfo_rooty()
            w = self.win.winfo_width()
            h = self.win.winfo_height()
            register_region(MASK_NAME, x - 4, y - 4, x + w + 4, y + h + 4)
        except tk.TclError:
            pass
