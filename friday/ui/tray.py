"""System tray launcher for Friday Control Center."""

from __future__ import annotations

import threading
import webbrowser
from pathlib import Path

from friday.config import SERVER_HOST, SERVER_PORT


def _open_ui() -> None:
    webbrowser.open(f"http://{SERVER_HOST}:{SERVER_PORT}/")


def start_tray(server_thread: threading.Thread | None = None) -> None:
    try:
        import pystray
        from PIL import Image, ImageDraw
    except ImportError:
        print("[Tray] pystray/Pillow missing — open UI in browser only.")
        _open_ui()
        if server_thread:
            server_thread.join()
        return

    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((4, 4, 60, 60), fill=(232, 93, 48))
    d.ellipse((22, 22, 42, 42), fill=(18, 18, 22))

    def on_open(icon, item) -> None:  # noqa: ARG001
        _open_ui()

    def on_quit(icon, item) -> None:  # noqa: ARG001
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("Open Friday", on_open, default=True),
        pystray.MenuItem("Quit", on_quit),
    )
    icon = pystray.Icon("friday", img, "Friday", menu)
    _open_ui()
    icon.run()
