"""Browser UI must wait until the HTTP server answers."""

from __future__ import annotations

from unittest.mock import patch

from friday.ui import tray


def test_wait_for_server_succeeds_when_health_ok():
    class _Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    with patch("friday.ui.tray.urllib.request.urlopen", return_value=_Resp()):
        assert tray.wait_for_server(timeout_s=2.0, poll_s=0.05) is True


def test_wait_for_server_times_out():
    import urllib.error

    with patch(
        "friday.ui.tray.urllib.request.urlopen",
        side_effect=urllib.error.URLError("down"),
    ):
        assert tray.wait_for_server(timeout_s=0.35, poll_s=0.1) is False


def test_open_ui_waits_before_browser():
    opened = []
    order = []

    def fake_wait(**kwargs):
        order.append("wait")
        return True

    def fake_open(url):
        order.append("open")
        opened.append(url)

    with patch.object(tray, "wait_for_server", side_effect=fake_wait):
        with patch.object(tray.webbrowser, "open", side_effect=fake_open):
            tray._open_ui(wait=True)
    assert order == ["wait", "open"]
    assert opened and opened[0].startswith("http://")
