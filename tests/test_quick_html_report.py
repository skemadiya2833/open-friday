"""Quick research = search + HTML, not the slow dossier pipeline."""

from __future__ import annotations

from unittest.mock import patch

from friday.reports.quick_html import run_quick_html_report


def test_quick_html_builds_from_search(tmp_path, monkeypatch):
    monkeypatch.setattr("friday.reports.store.DATA_DIR", str(tmp_path))
    monkeypatch.setattr("friday.config.DATA_DIR", str(tmp_path))
    rows = [
        {"title": "Batman", "url": "https://en.wikipedia.org/wiki/Batman", "snippet": "DC Comics character."},
        {"title": "Batman (film)", "url": "https://example.com/batman", "snippet": "1989 film."},
    ]
    opened = []

    imgs = [
        {"image": "https://upload.wikimedia.org/wikipedia/en/c/c7/Batman_Infobox.jpg", "url": "https://en.wikipedia.org/wiki/Batman", "title": "Batman"},
        {"image": "https://upload.wikimedia.org/wikipedia/commons/thumb/3/3d/x.jpg/640px-x.jpg", "url": "https://commons.wikimedia.org", "title": "Batman Merkez"},
    ]
    with patch("friday.knowledge.search.fetch_web_results", return_value=rows):
        with patch("friday.knowledge.enrich.wikipedia_brief", return_value=None):
            with patch("friday.knowledge.enrich.collect_topic_images", return_value=imgs):
                with patch(
                    "friday.reports.quick_html._open_html",
                    side_effect=lambda html, stem="x": opened.append(html) or tmp_path / "out.html",
                ):
                    doc = run_quick_html_report("batman", save=True, open_browser=True)

    assert doc["mode"] == "quick"
    assert len(doc["sources"]) == 2
    assert len(doc["findings"]) == 2
    assert len(doc["images"]) == 2
    assert "Batman" in doc["summary"]["tldr"] or "DC" in doc["summary"]["tldr"]
    assert opened and "Batman_Infobox.jpg" in opened[0]
    assert 'class="gallery"' in opened[0]
    assert (tmp_path / "reports").exists() or doc.get("id")
