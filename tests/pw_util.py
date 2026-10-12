"""Playwright helpers for tests that need a real Chromium binary."""

from __future__ import annotations

import pytest


def chromium_available() -> bool:
    """True only when Playwright is installed *and* a Chromium binary can launch."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return False
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            browser.close()
        return True
    except Exception:
        return False


requires_chromium = pytest.mark.skipif(
    not chromium_available(),
    reason="Playwright Chromium not installed (run: playwright install chromium)",
)
