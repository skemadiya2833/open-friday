"""System tray launcher for Friday Control Center."""

from __future__ import annotations

import threading
import webbrowser

from friday.config import SERVER_PORT, ui_host


def _open_ui() -> None:
    webbrowser.open(f"http://{ui_host()}:{SERVER_PORT}/")


def start_tray(server_thread: threading.Thread | None = None) -> None:
    try:
        import pystray
        from PIL import Image, ImageDraw
    except ImportError:
        print("[Tray] pystray/Pillow missing — open UI in browser only.")
        from friday.shutdown import install_ctrl_c, request_stop

        install_ctrl_c()
        _open_ui()
        if server_thread:
            try:
                server_thread.join()
            except KeyboardInterrupt:
                request_stop(0)
        return

    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((4, 4, 60, 60), fill=(232, 93, 48))
    d.ellipse((22, 22, 42, 42), fill=(18, 18, 22))

    def on_open(icon, item) -> None:  # noqa: ARG001
        _open_ui()

    def on_quit(icon, item) -> None:  # noqa: ARG001
        from friday.shutdown import request_stop

        icon.stop()
        request_stop(0)

    menu = pystray.Menu(
        pystray.MenuItem("Open Friday", on_open, default=True),
        pystray.MenuItem("Quit", on_quit),
    )
    icon = pystray.Icon("friday", img, "Friday", menu)
    from friday.shutdown import install_ctrl_c, request_stop

    install_ctrl_c(on_stop=icon.stop)
    _open_ui()
    print("[Friday] Stop → Ctrl+C in this window, or Quit on the tray icon.", flush=True)
    try:
        icon.run()
    except KeyboardInterrupt:
        request_stop(0)
