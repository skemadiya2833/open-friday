"""
Friday Control Center — full desktop GUI for the vision agent.

Composition: brand hero strip + live vision plane + operator controls.
Runs the agent on a worker thread; UI updates arrive via the event bus.
"""

from __future__ import annotations

import platform
import queue
import threading
import tkinter as tk
from tkinter import font as tkfont
from typing import Any

from PIL import Image, ImageTk

from friday.agent.control import AgentController
from friday.config import LOW_END_MODE, MODEL_NAME, OLLAMA_HOST
from friday.ui.events import AgentEvent, get_bus, reset_bus
from friday.ui.mask import clear_regions, register_region, unregister_region
from friday.ui.status_popup import StatusPopup

# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------

C = {
    "bg": "#0c1014",
    "panel": "#121820",
    "panel2": "#161e28",
    "line": "#1e2a36",
    "fg": "#e6edf3",
    "muted": "#7d8b99",
    "dim": "#4a5866",
    "brand": "#3dd6c6",
    "brand_dim": "#1f6f68",
    "accent": "#f0b429",
    "think": "#9bb8ff",
    "ok": "#3ecf8e",
    "warn": "#f0b429",
    "bad": "#f07178",
    "live": "#3ecf8e",
    "input_bg": "#0a0e12",
    "btn": "#1a2733",
    "btn_go": "#0d3d38",
    "btn_stop": "#3d1518",
    "btn_pause": "#3d3010",
}

STATUS_COLOR = {
    "idle": C["muted"],
    "live": C["live"],
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

EXAMPLE_TASKS = [
    "Open Notepad and type Hello from Friday",
    "Open Chrome and search for wireless headphones",
    "Open Calculator and compute 144 * 12",
]


def _action_label(step: dict | None) -> str:
    if not step:
        return "—"
    act = str(step.get("action") or "").upper()
    if act in ("CLICK", "DOUBLE_CLICK", "RIGHT_CLICK", "HOVER", "MIDDLE_CLICK"):
        return f"{act}  ({step.get('x')}, {step.get('y')})"
    if act in ("TYPE", "PASTE", "WIN_SEARCH", "SEARCH", "KNOWLEDGE_SEARCH"):
        text = step.get("text") or step.get("query") or ""
        preview = text[:42] + ("…" if len(text) > 42 else "")
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
    desc = (step.get("description") or "")[:48]
    return f"{act}: {desc}" if desc else act


class FridayApp:
    """Main operator GUI."""

    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Friday")
        self.root.configure(bg=C["bg"])
        self.root.minsize(980, 640)
        self.root.geometry("1180x720")

        self._events: queue.Queue[AgentEvent] = queue.Queue()
        self._controller: AgentController | None = None
        self._worker: threading.Thread | None = None
        self._running = False
        self._paused = False
        self._frame_photo: ImageTk.PhotoImage | None = None
        self._latest_frame: Image.Image | None = None
        self._status = "idle"
        self._iteration = 0
        self._approval_step: dict | None = None
        self._status_popup: StatusPopup | None = None
        self._main_hidden = False
        self._objective = ""

        self._fonts = self._build_fonts()
        self._build()
        self._bind_events()
        self._poll_events()
        self.root.after(400, self._update_mask_region)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        if platform.system() == "Windows":
            try:
                self.root.state("zoomed")
            except tk.TclError:
                pass

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _build_fonts(self) -> dict[str, tkfont.Font]:
        mono_family = "Cascadia Mono"
        try:
            probe = tkfont.Font(family=mono_family, size=10)
            if "cascadia" not in probe.actual("family").lower():
                mono_family = "Consolas"
        except tk.TclError:
            mono_family = "Consolas"

        return {
            "brand": tkfont.Font(family="Segoe UI Semibold", size=28),
            "brand_sm": tkfont.Font(family="Segoe UI Semibold", size=11),
            "title": tkfont.Font(family="Segoe UI Semibold", size=12),
            "body": tkfont.Font(family="Segoe UI", size=10),
            "small": tkfont.Font(family="Segoe UI", size=9),
            "mono": tkfont.Font(family=mono_family, size=10),
            "mono_sm": tkfont.Font(family=mono_family, size=9),
            "status": tkfont.Font(family=mono_family, size=10, weight="bold"),
        }

    def _build(self) -> None:
        f = self._fonts
        root = self.root

        # Brand strip
        hero = tk.Frame(root, bg=C["bg"], height=78)
        hero.pack(fill="x", padx=28, pady=(18, 0))
        hero.pack_propagate(False)

        brand_row = tk.Frame(hero, bg=C["bg"])
        brand_row.pack(side="left", anchor="s")
        tk.Label(
            brand_row, text="FRIDAY", font=f["brand"], bg=C["bg"], fg=C["brand"],
        ).pack(anchor="w")
        tk.Label(
            brand_row,
            text="Vision-driven autonomous operator",
            font=f["small"], bg=C["bg"], fg=C["muted"],
        ).pack(anchor="w")

        meta = tk.Frame(hero, bg=C["bg"])
        meta.pack(side="right", anchor="s")
        self.model_lbl = tk.Label(
            meta, text=f"{MODEL_NAME}", font=f["mono_sm"],
            bg=C["bg"], fg=C["dim"],
        )
        self.model_lbl.pack(anchor="e")
        self.host_lbl = tk.Label(
            meta, text=OLLAMA_HOST, font=f["mono_sm"],
            bg=C["bg"], fg=C["dim"],
        )
        self.host_lbl.pack(anchor="e")

        # Accent rule under brand
        tk.Frame(root, bg=C["brand_dim"], height=2).pack(fill="x", padx=28, pady=(10, 14))

        # Body: vision | ops
        body = tk.Frame(root, bg=C["bg"])
        body.pack(fill="both", expand=True, padx=28, pady=(0, 18))

        left = tk.Frame(body, bg=C["bg"])
        left.pack(side="left", fill="both", expand=True, padx=(0, 14))

        right = tk.Frame(body, bg=C["bg"], width=380)
        right.pack(side="right", fill="y")
        right.pack_propagate(False)

        self._build_vision(left)
        self._build_ops(right)

    def _section(self, parent: tk.Widget, title: str) -> tk.Frame:
        wrap = tk.Frame(parent, bg=C["bg"])
        tk.Label(
            wrap, text=title, font=self._fonts["brand_sm"],
            bg=C["bg"], fg=C["muted"], anchor="w",
        ).pack(fill="x", pady=(0, 6))
        return wrap

    def _build_vision(self, parent: tk.Frame) -> None:
        f = self._fonts
        hdr = self._section(parent, "LIVE VISION")
        hdr.pack(fill="x")

        status_row = tk.Frame(hdr, bg=C["bg"])
        status_row.pack(fill="x", pady=(0, 6))
        self.status_dot = tk.Label(
            status_row, text="●", font=f["status"], bg=C["bg"], fg=C["muted"],
        )
        self.status_dot.pack(side="left")
        self.status_lbl = tk.Label(
            status_row, text="IDLE", font=f["status"],
            bg=C["bg"], fg=C["muted"],
        )
        self.status_lbl.pack(side="left", padx=(6, 0))
        self.tick_lbl = tk.Label(
            status_row, text="tick 0", font=f["mono_sm"],
            bg=C["bg"], fg=C["dim"],
        )
        self.tick_lbl.pack(side="right")

        self.vision_frame = tk.Frame(parent, bg=C["panel"], highlightthickness=1, highlightbackground=C["line"])
        self.vision_frame.pack(fill="both", expand=True)

        self.vision_lbl = tk.Label(
            self.vision_frame,
            text="Start a task to begin observing the desktop",
            font=f["body"], bg=C["panel"], fg=C["dim"],
        )
        self.vision_lbl.pack(expand=True, fill="both", padx=2, pady=2)

        # Observation strip under vision
        obs_wrap = self._section(parent, "OBSERVATION")
        obs_wrap.pack(fill="x", pady=(14, 0))
        self.obs_lbl = tk.Label(
            parent, text="Waiting for the first screen read…",
            font=f["body"], bg=C["bg"], fg=C["fg"],
            anchor="w", justify="left", wraplength=680,
        )
        self.obs_lbl.pack(fill="x")

    def _build_ops(self, parent: tk.Frame) -> None:
        f = self._fonts

        # Task
        task_sec = self._section(parent, "OBJECTIVE")
        task_sec.pack(fill="x")

        self.task_box = tk.Text(
            parent, height=4, font=f["body"],
            bg=C["input_bg"], fg=C["fg"], insertbackground=C["brand"],
            relief="flat", highlightthickness=1, highlightbackground=C["line"],
            wrap="word", padx=10, pady=8,
        )
        self.task_box.pack(fill="x")
        self.task_box.insert("1.0", EXAMPLE_TASKS[0])
        self.task_box.bind("<Control-Return>", lambda _e: self._start_task())

        examples = tk.Frame(parent, bg=C["bg"])
        examples.pack(fill="x", pady=(8, 0))
        for sample in EXAMPLE_TASKS:
            btn = tk.Label(
                examples, text=sample[:38] + ("…" if len(sample) > 38 else ""),
                font=f["small"], bg=C["panel2"], fg=C["muted"],
                padx=8, pady=4, cursor="hand2",
            )
            btn.pack(fill="x", pady=2)
            btn.bind("<Button-1>", lambda _e, s=sample: self._set_task(s))
            btn.bind("<Enter>", lambda e: e.widget.config(fg=C["brand"]))
            btn.bind("<Leave>", lambda e: e.widget.config(fg=C["muted"]))

        # Controls
        ctrl = tk.Frame(parent, bg=C["bg"])
        ctrl.pack(fill="x", pady=(14, 0))

        self.go_btn = self._button(ctrl, "Start", C["btn_go"], C["brand"], self._start_task)
        self.go_btn.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.pause_btn = self._button(ctrl, "Pause", C["btn_pause"], C["warn"], self._toggle_pause)
        self.pause_btn.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.pause_btn.config(state="disabled")

        self.stop_btn = self._button(ctrl, "Stop", C["btn_stop"], C["bad"], self._stop_task)
        self.stop_btn.pack(side="left", fill="x", expand=True)
        self.stop_btn.config(state="disabled")

        # Approval banner slot (shown only when needed)
        self.approval_frame = tk.Frame(parent, bg="#2a1f10")
        self.approval_lbl = tk.Label(
            self.approval_frame, text="", font=f["body"],
            bg="#2a1f10", fg=C["warn"], wraplength=340, justify="left",
            padx=10, pady=8,
        )
        self.approval_lbl.pack(fill="x")
        row = tk.Frame(self.approval_frame, bg="#2a1f10")
        row.pack(fill="x", padx=10, pady=(0, 10))
        self._button(row, "Approve", "#14532d", C["ok"], lambda: self._resolve_approval(True)).pack(
            side="left", padx=(0, 8),
        )
        self._button(row, "Reject", "#7f1d1d", C["bad"], lambda: self._resolve_approval(False)).pack(
            side="left",
        )

        # Next action
        act_sec = self._section(parent, "NEXT ACTION")
        act_sec.pack(fill="x", pady=(18, 0))
        self.action_lbl = tk.Label(
            parent, text="—", font=f["mono"], bg=C["panel"], fg=C["accent"],
            anchor="w", justify="left", padx=10, pady=10,
            wraplength=340,
        )
        self.action_lbl.pack(fill="x")

        # Reasoning
        think_sec = self._section(parent, "REASONING")
        think_sec.pack(fill="x", pady=(14, 0))
        think_frame = tk.Frame(parent, bg=C["panel"], height=150)
        think_frame.pack(fill="both", expand=False)
        think_frame.pack_propagate(False)
        self.think_text = tk.Text(
            think_frame, font=f["small"], bg=C["panel"], fg=C["think"],
            relief="flat", highlightthickness=0, wrap="word",
            state="disabled", padx=8, pady=8,
        )
        self.think_text.pack(fill="both", expand=True)

        # History
        hist_sec = self._section(parent, "HISTORY")
        hist_sec.pack(fill="x", pady=(14, 0))
        hist_frame = tk.Frame(parent, bg=C["panel"])
        hist_frame.pack(fill="both", expand=True)
        self.hist_text = tk.Text(
            hist_frame, font=f["mono_sm"], bg=C["panel"], fg=C["fg"],
            relief="flat", highlightthickness=0, wrap="word",
            state="disabled", padx=8, pady=8,
        )
        self.hist_text.pack(fill="both", expand=True)

    def _button(
        self,
        parent: tk.Widget,
        text: str,
        bg: str,
        fg: str,
        command,
    ) -> tk.Button:
        return tk.Button(
            parent, text=text, font=self._fonts["body"],
            bg=bg, fg=fg, activebackground=bg, activeforeground=fg,
            relief="flat", padx=12, pady=8, cursor="hand2",
            command=command,
        )

    # ------------------------------------------------------------------
    # Event wiring
    # ------------------------------------------------------------------

    def _bind_events(self) -> None:
        reset_bus()
        get_bus().subscribe_all(self._on_bus_event)
        self.root.bind("<Configure>", lambda _e: self._schedule_mask_update())

    def _on_bus_event(self, event: AgentEvent) -> None:
        # Drop intermediate live frames if the UI is behind (keep latest via queue drain)
        self._events.put(event)

    def _poll_events(self) -> None:
        latest_frame: AgentEvent | None = None
        try:
            while True:
                event = self._events.get_nowait()
                if event.type == "live_frame":
                    latest_frame = event
                else:
                    self._handle_event(event)
        except queue.Empty:
            pass

        if latest_frame is not None:
            self._handle_event(latest_frame)

        poll_ms = 80 if LOW_END_MODE else 50
        self.root.after(poll_ms, self._poll_events)

    def _handle_event(self, event: AgentEvent) -> None:
        t = event.type
        p = event.payload
        popup = self._status_popup

        if t == "live_frame":
            image = p.get("image")
            if image is not None:
                self._show_frame(image, int(p.get("frame_index") or 0))
            return

        if t == "status":
            status = str(p.get("status") or "idle")
            self._set_status(status)
            if popup is not None:
                popup.set_status(status)
            return

        if t == "tick":
            self._iteration = int(p.get("iteration") or 0)
            self.tick_lbl.config(text=f"tick {self._iteration}")
            if popup is not None:
                popup.set_tick(self._iteration)
            return

        if t == "thinking_clear":
            self._set_thinking("")
            if popup is not None:
                popup.set_thinking("")
            return

        if t == "thinking_token":
            token = str(p.get("token") or "")
            self._append_thinking(token)
            if popup is not None:
                popup.append_thinking(token)
            return

        if t == "thinking_set":
            text = str(p.get("text") or "")
            self._set_thinking(text)
            if popup is not None:
                popup.set_thinking(text)
            return

        if t == "decision":
            obs = str(p.get("observation") or "")
            if obs:
                self.obs_lbl.config(text=obs)
            step = p.get("step")
            msg = str(p.get("message") or "")
            label = _action_label(step) if step else "—"
            if msg:
                label = f"{label}\n{msg}"
            self.action_lbl.config(text=label)
            if popup is not None:
                popup.set_action(step if isinstance(step, dict) else None, msg)
            return

        if t == "action_start":
            step = p.get("step")
            if popup is not None and isinstance(step, dict):
                popup.set_action(step)
            return

        if t == "action_end":
            history = p.get("history") or []
            self._set_history(history)
            return

        if t == "approval_request":
            step = p.get("step") or {}
            self._show_approval(step)
            if popup is not None and isinstance(step, dict):
                popup.show_approval(step)
            return

        if t == "approval_resolved":
            self._hide_approval()
            if popup is not None:
                popup.hide_approval()
            return

        if t == "session_end":
            self._on_session_finished(str(p.get("status") or ""))
            return

        if t == "control":
            action = p.get("action")
            if action == "pause":
                self._paused = True
                self.pause_btn.config(text="Resume")
                if popup is not None:
                    popup.set_paused(True)
            elif action == "resume":
                self._paused = False
                self.pause_btn.config(text="Pause")
                if popup is not None:
                    popup.set_paused(False)

    # ------------------------------------------------------------------
    # UI helpers
    # ------------------------------------------------------------------

    def _set_status(self, status: str) -> None:
        self._status = status
        color = STATUS_COLOR.get(status, C["muted"])
        self.status_dot.config(fg=color)
        self.status_lbl.config(text=status.upper(), fg=color)

    def _show_frame(self, pil_image: Image.Image, frame_index: int) -> None:
        self._latest_frame = pil_image
        w = max(320, self.vision_frame.winfo_width() - 8)
        h = max(200, self.vision_frame.winfo_height() - 8)
        resample = Image.Resampling.BILINEAR if LOW_END_MODE else Image.Resampling.LANCZOS
        thumb = pil_image.copy()
        thumb.thumbnail((w, h), resample)
        self._frame_photo = ImageTk.PhotoImage(thumb)
        self.vision_lbl.config(image=self._frame_photo, text="")
        if frame_index and self._status in ("idle", "live", "running"):
            self.tick_lbl.config(text=f"tick {self._iteration}  ·  frame {frame_index}")

    def _set_thinking(self, text: str) -> None:
        self.think_text.config(state="normal")
        self.think_text.delete("1.0", "end")
        if text:
            self.think_text.insert("1.0", text)
        self.think_text.config(state="disabled")

    def _append_thinking(self, token: str) -> None:
        self.think_text.config(state="normal")
        self.think_text.insert("end", token)
        content = self.think_text.get("1.0", "end")
        if len(content) > 2500:
            self.think_text.delete("1.0", f"1.{len(content) - 2000}")
        self.think_text.see("end")
        self.think_text.config(state="disabled")

    def _set_history(self, entries: list[str]) -> None:
        self.hist_text.config(state="normal")
        self.hist_text.delete("1.0", "end")
        self.hist_text.insert("1.0", "\n".join(entries))
        self.hist_text.see("end")
        self.hist_text.config(state="disabled")

    def _show_approval(self, step: dict) -> None:
        self._approval_step = step
        summary = _action_label(step)
        desc = step.get("description") or ""
        text = f"Approval required\n{summary}"
        if desc:
            text += f"\n{desc}"
        self.approval_lbl.config(text=text)
        if not self.approval_frame.winfo_ismapped():
            self.approval_frame.pack(fill="x", pady=(12, 0), after=self.stop_btn.master)
        self._set_status("waiting for approval")

    def _hide_approval(self) -> None:
        self._approval_step = None
        if self.approval_frame.winfo_ismapped():
            self.approval_frame.pack_forget()

    def _resolve_approval(self, approved: bool) -> None:
        if self._controller is not None:
            self._controller.resolve_approval(approved)
        self._hide_approval()

    def _set_task(self, text: str) -> None:
        self.task_box.delete("1.0", "end")
        self.task_box.insert("1.0", text)
        self.task_box.focus_set()

    # ------------------------------------------------------------------
    # Agent control
    # ------------------------------------------------------------------

    def _start_task(self) -> None:
        if self._running:
            return
        objective = self.task_box.get("1.0", "end").strip()
        if not objective:
            self.obs_lbl.config(text="Enter an objective before starting.")
            return

        self._running = True
        self._paused = False
        self._iteration = 0
        self._objective = objective
        self.go_btn.config(state="disabled")
        self.pause_btn.config(state="normal", text="Pause")
        self.stop_btn.config(state="normal")
        self.task_box.config(state="disabled")
        self._set_thinking("")
        self._set_history([])
        self.action_lbl.config(text="—")
        self.obs_lbl.config(text="Observing…")
        self._set_status("running")

        self._controller = AgentController()
        self._show_status_popup(objective)
        self._hide_main_window()

        # Defer the agent + live feed until the window has actually minimized.
        # Otherwise the first captured frames catch the still-maximized control
        # center, which is masked black — and the model "sees" nothing.
        self.root.after(450, lambda: self._launch_worker(objective))

    def _launch_worker(self, objective: str) -> None:
        if not self._running or self._controller is None:
            return

        def worker() -> None:
            from friday.agent.loop import run_agent
            try:
                run_agent(
                    objective,
                    controller=self._controller,
                    use_overlay=False,
                )
            except Exception as exc:
                get_bus().emit("status", status="error")
                get_bus().emit("session_end", status="failed", error=str(exc))
                print(f"[GUI] Agent error: {exc}")

        self._worker = threading.Thread(target=worker, name="FridayAgent", daemon=True)
        self._worker.start()

    def _toggle_pause(self) -> None:
        if not self._controller or not self._running:
            return
        if self._paused:
            self._controller.resume()
            self._paused = False
            self.pause_btn.config(text="Pause")
            self._set_status("live")
            if self._status_popup is not None:
                self._status_popup.set_paused(False)
                self._status_popup.set_status("live")
        else:
            self._controller.pause()
            self._paused = True
            self.pause_btn.config(text="Resume")
            self._set_status("paused")
            if self._status_popup is not None:
                self._status_popup.set_paused(True)
                self._status_popup.set_status("paused")

    def _stop_task(self) -> None:
        if self._controller is not None:
            self._controller.request_cancel()
        self._set_status("halt")
        if self._status_popup is not None:
            self._status_popup.set_status("halt")

    def _on_session_finished(self, status: str) -> None:
        self._running = False
        self._paused = False
        self._controller = None
        self.go_btn.config(state="normal")
        self.pause_btn.config(state="disabled", text="Pause")
        self.stop_btn.config(state="disabled")
        self.task_box.config(state="normal")
        self._hide_approval()
        self._close_status_popup()
        self._restore_main_window()
        if status == "completed":
            self._set_status("complete")
            self.obs_lbl.config(text="Task complete.")
        elif status in ("halted", "halt"):
            self._set_status("halt")
            self.obs_lbl.config(text="Stopped.")
        elif status:
            self._set_status("error" if status not in STATUS_COLOR else status)

    # ------------------------------------------------------------------
    # Status popup + window hide/show
    # ------------------------------------------------------------------

    def _show_status_popup(self, objective: str) -> None:
        self._close_status_popup()
        self._status_popup = StatusPopup(
            self.root,
            on_pause=self._toggle_pause,
            on_stop=self._stop_task,
            on_approve=self._resolve_approval,
            on_restore=self._restore_main_window,
        )
        self._status_popup.set_task(objective)
        self._status_popup.set_status("running")
        self._status_popup.set_tick(0)
        self._status_popup.set_action(None)
        self._status_popup.set_thinking("")

    def _close_status_popup(self) -> None:
        if self._status_popup is not None:
            self._status_popup.destroy()
            self._status_popup = None

    def _hide_main_window(self) -> None:
        """Minimize the control center so the desktop is free for the agent."""
        unregister_region("friday_gui")
        self._main_hidden = True
        # Minimize only the main HWND so the status popup (child Toplevel)
        # is not forced iconic along with Tk's iconify cascade.
        if platform.system() == "Windows":
            try:
                import ctypes
                user32 = ctypes.windll.user32
                hwnd = user32.GetParent(int(self.root.winfo_id()))
                if not hwnd:
                    hwnd = int(self.root.winfo_id())
                SW_SHOWMINNOACTIVE = 7
                user32.ShowWindow(hwnd, SW_SHOWMINNOACTIVE)
            except Exception:
                try:
                    self.root.iconify()
                except tk.TclError:
                    pass
        else:
            try:
                self.root.iconify()
            except tk.TclError:
                try:
                    self.root.withdraw()
                except tk.TclError:
                    pass
        self.root.after(30, self._ensure_popup_visible)
        self.root.after(150, self._ensure_popup_visible)

    def _ensure_popup_visible(self) -> None:
        popup = self._status_popup
        if popup is None:
            return
        popup.force_visible()

    def _restore_main_window(self) -> None:
        was_hidden = self._main_hidden
        try:
            state = str(self.root.state())
            was_hidden = was_hidden or state in ("iconic", "withdrawn")
        except tk.TclError:
            pass
        self._main_hidden = False
        try:
            if platform.system() == "Windows":
                try:
                    import ctypes
                    user32 = ctypes.windll.user32
                    hwnd = user32.GetParent(int(self.root.winfo_id()))
                    if not hwnd:
                        hwnd = int(self.root.winfo_id())
                    SW_RESTORE = 9
                    user32.ShowWindow(hwnd, SW_RESTORE)
                except Exception:
                    pass
            self.root.deiconify()
            if platform.system() == "Windows":
                try:
                    self.root.state("zoomed")
                except tk.TclError:
                    pass
            self.root.lift()
            self.root.focus_force()
        except tk.TclError:
            pass
        if was_hidden:
            self.root.after(200, self._update_mask_region)
        if self._running and self._status_popup is not None:
            self.root.after(50, self._ensure_popup_visible)

    # ------------------------------------------------------------------
    # Mask Friday window from vision
    # ------------------------------------------------------------------

    def _schedule_mask_update(self) -> None:
        if self._main_hidden:
            return
        if not hasattr(self, "_mask_job"):
            self._mask_job = None
        if self._mask_job is not None:
            self.root.after_cancel(self._mask_job)
        self._mask_job = self.root.after(200, self._update_mask_region)

    def _update_mask_region(self) -> None:
        if self._main_hidden:
            unregister_region("friday_gui")
            return
        try:
            self.root.update_idletasks()
            x = self.root.winfo_rootx()
            y = self.root.winfo_rooty()
            w = self.root.winfo_width()
            h = self.root.winfo_height()
            # Pad slightly so window chrome is covered
            register_region("friday_gui", x - 4, y - 4, x + w + 4, y + h + 4)
        except tk.TclError:
            pass

    def _on_close(self) -> None:
        if self._controller is not None:
            self._controller.request_cancel()
        self._close_status_popup()
        unregister_region("friday_gui")
        clear_regions()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def launch_gui() -> None:
    FridayApp().run()


if __name__ == "__main__":
    launch_gui()
