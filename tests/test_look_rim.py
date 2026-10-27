"""Screen look rim — orange edge glow helper."""

from __future__ import annotations

from friday.ui.look_rim import build_rim_image, status


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
