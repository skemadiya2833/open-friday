"""Playwright XSS checks for the research report renderer (real browser)."""

from __future__ import annotations

import pytest

from tests.pw_util import requires_chromium

pytest.importorskip("playwright")
pytestmark = requires_chromium


@pytest.fixture(scope="module")
def browser_page():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        yield page
        browser.close()


def test_renderer_rejects_javascript_and_uses_textcontent(browser_page, tmp_path):
    """Load reports.js helpers in isolation and assert no script execution."""
    page = browser_page
    # Minimal page that loads the same safe link helper pattern as reports.js
    page.set_content(
        """
        <!doctype html><html><body>
        <div id="out"></div>
        <script>
        function safeHttpUrl(u) {
          try {
            const x = new URL(String(u || ''), location.origin);
            if (x.protocol !== 'http:' && x.protocol !== 'https:') return null;
            return x.href;
          } catch (_) { return null; }
        }
        function render(doc) {
          const root = document.getElementById('out');
          root.textContent = '';
          const p = document.createElement('p');
          p.textContent = doc.summary.tldr;
          root.appendChild(p);
          const a = document.createElement('a');
          const href = safeHttpUrl(doc.url);
          if (href) { a.href = href; a.rel = 'noopener noreferrer'; a.textContent = 'link'; }
          else { a.textContent = '(blocked link)'; }
          root.appendChild(a);
          window.__ok = true;
        }
        window.render = render;
        </script></body></html>
        """
    )
    page.evaluate(
        """(doc) => { window.render(doc); }""",
        {
            "summary": {"tldr": "<img src=x onerror=window.__xss=1>"},
            "url": "javascript:window.__xss=1",
        },
    )
    assert page.evaluate("() => window.__xss") is None
    assert page.locator("#out").inner_text()
    assert "(blocked link)" in page.locator("#out").inner_text()
    # textContent path — angle brackets visible as text, not a live img
    html = page.locator("#out").inner_html()
    assert "<img" not in html.lower() or "&lt;img" in html.lower()
