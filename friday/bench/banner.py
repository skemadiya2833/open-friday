"""Always-on-top on-screen notice shown while a live benchmark drives the desktop."""

from __future__ import annotations

import ctypes
import queue
import threading


class Banner:
    def __init__(self) -> None:
        self._q: queue.Queue[str | None] = queue.Queue()
        self._t = threading.Thread(target=self._run, name="BenchBanner", daemon=True)
        self._ready = threading.Event()

    def start(self) -> None:
        self._t.start()
        self._ready.wait(5)

    def set(self, text: str) -> None:
        self._q.put(text)

    def close(self) -> None:
        self._q.put(None)

    def _run(self) -> None:
        try:
            import tkinter as tk

            u = ctypes.windll.user32
            n_mon = u.GetSystemMetrics(80)                 # SM_CMONITORS
            pw = u.GetSystemMetrics(0)                     # primary width
            root = tk.Tk()
            root.overrideredirect(True)
            root.attributes("-topmost", True)
            root.configure(bg="#b00020")
            w, h = 760, 70
            # Second monitor if there is one (keeps it out of the agent's screenshots), else top-right.
            x, y = (pw + 40, 20) if n_mon > 1 else (max(0, pw - w - 10), 0)
            root.geometry(f"{w}x{h}+{x}+{y}")
            var = tk.StringVar(value="Friday benchmark starting")
            tk.Label(root, textvariable=var, fg="white", bg="#b00020", font=("Segoe UI", 14, "bold"),
                     wraplength=w - 20, justify="center").pack(expand=True, fill="both")
            self._ready.set()

            def pump():
                try:
                    while True:
                        item = self._q.get_nowait()
                        if item is None:
                            root.destroy()
                            return
                        var.set(item)
                except queue.Empty:
                    pass
                root.after(200, pump)

            root.after(200, pump)
            root.mainloop()
        except Exception:  # noqa: BLE001 - banner is a courtesy, never fatal
            self._ready.set()
