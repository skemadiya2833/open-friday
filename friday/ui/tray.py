"""System tray launcher for Friday Control Center."""

from __future__ import annotations

import threading
import time
import urllib.error
import urllib.request
import webbrowser

from friday.config import SERVER_PORT, ui_host


def ui_url() -> str:
    return f"http://{ui_host()}:{SERVER_PORT}/"


def wait_for_server(*, timeout_s: float = 60.0, poll_s: float = 0.25) -> bool:
    """Block until the Control Center HTTP API answers, or timeout."""
    health = f"http://{ui_host()}:{SERVER_PORT}/api/health"
    deadline = time.monotonic() + max(1.0, timeout_s)
    last_err = ""
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(health, timeout=1.5) as resp:  # noqa: S310
                if 200 <= getattr(resp, "status", 200) < 500:
                    return True
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_err = str(exc)
        time.sleep(poll_s)
    if last_err:
        print(f"[Friday] Server not ready after {timeout_s:.0f}s ({last_err})", flush=True)
    return False


def _open_ui(*, wait: bool = True) -> None:
    """Open the HUD only after the server is accepting requests (default)."""
    if wait and not wait_for_server():
        print("[Friday] Opening UI anyway — refresh if the page fails to load.", flush=True)
    webbrowser.open(ui_url())


def start_tray(server_thread: threading.Thread | None = None) -> None:
    try:
        import pystray
        from PIL import Image, ImageDraw
    except ImportError:
        print("[Tray] pystray/Pillow missing — open UI in browser only.")
        from friday.shutdown import install_ctrl_c, request_stop

        install_ctrl_c()
        print("[Friday] Waiting for server before opening browser…", flush=True)
        _open_ui(wait=True)
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
        # Manual open: short wait in case the user clicked before bind finished.
        _open_ui(wait=True)

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

    def _open_when_ready() -> None:
        print("[Friday] Waiting for server before opening browser…", flush=True)
        _open_ui(wait=True)

    # Never block the tray message loop on readiness — poll in a daemon thread.
    threading.Thread(target=_open_when_ready, name="FridayOpenUI", daemon=True).start()
    print("[Friday] Stop → Ctrl+C in this window, or Quit on the tray icon.", flush=True)
    try:
        icon.run()
    except KeyboardInterrupt:
        request_stop(0)
