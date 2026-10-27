"""Screen look rim — orange edge glow helper."""

from __future__ import annotations

from friday.ui import look_rim
from friday.ui.look_rim import build_rim_image, looking, status


def test_build_rim_has_orange_on_edges():
    img = build_rim_image(200, 120, pulse=0.0)
    assert img.size == (200, 120)
    assert img.mode == "RGBA"
    # Corner / edge pixels should be non-transparent orange-ish
    px = img.getpixel((2, 2))
    assert px[3] > 40
    assert px[0] > px[2]  # red > blue
    # Center should stay clear
    mid = img.getpixel((100, 60))
    assert mid[3] == 0


def test_status_shape():
    st = status()
    assert "looking" in st and "enabled" in st


def test_looking_context_is_noop_under_pytest():
    """Must not spawn Win32 rim threads during pytest (CI access-violation)."""
    assert look_rim._headless_or_test() is True
    assert look_rim._enabled() is False
    with looking():
        st = status()
        assert st["looking"] is True
        assert st["enabled"] is False
    assert status()["looking"] is False
    ctrl = look_rim._controller
    assert ctrl is None or ctrl._running is False
