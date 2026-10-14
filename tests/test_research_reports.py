"""Stage W: research report schema, validation, XSS-safe renderer helpers, adversarial."""

from __future__ import annotations

import json


from friday.reports.schema_load import load_schema, validate_report_schema
from friday.reports.validate import evidence_in_source, validate_mechanics, value_in_snippet


def _minimal_doc(**overrides):
    base = {
        "schema_version": "1",
        "id": "abc123def456",
        "query": "test",
        "mode": "quick",
        "created_at": "2026-10-11T00:00:00Z",
        "summary": {"tldr": "Hello", "confidence": 0.5, "rationale": "ok"},
        "sources": [
            {
                "id": "s1",
                "url": "https://example.com/a",
                "title": "Example",
                "domain": "example.com",
                "fetched_at": "2026-10-11T00:00:00Z",
                "text": "The widget scored 42 points in trials.",
                "credibility": {"tag": "medium", "label": "heuristic:medium (rule-based; not a fact-check)", "heuristic": True},
            }
        ],
        "claims": [
            {
                "id": "c1",
                "claim": "Widget scored 42",
                "source_id": "s1",
                "evidence": "scored 42 points",
            }
        ],
        "trace": [{"step": "plan", "detail": "x"}],
    }
    base.update(overrides)
    return base


def test_schema_loads_and_accepts_minimal():
    assert load_schema()["$id"] == "friday://reports/v1"
    errs = validate_report_schema(_minimal_doc())
    assert errs == []


def test_fabricated_citation_rejected():
    doc = _minimal_doc(
        claims=[{
            "id": "c1",
            "claim": "Secret approval",
            "source_id": "s1",
            "evidence": "approve the pairing now",  # not in source text
        }]
    )
    out, issues = validate_mechanics(doc)
    assert not out["claims"]
    assert any("evidence not substring" in i for i in issues)


def test_evidence_whitespace_normalized():
    assert evidence_in_source("scored   42\npoints", "The widget scored 42 points in trials.")


def test_chart_value_must_appear_in_snippet():
    assert value_in_snippet(42, "scored 42 points")
    doc = _minimal_doc(
        charts=[{
            "id": "ch1",
            "title": "Scores",
            "kind": "bar",
            "series": [{
                "label": "A",
                "value": 99,
                "source_id": "s1",
                "snippet": "scored 42 points",
            }],
        }],
        claims=[],
    )
    out, issues = validate_mechanics(doc)
    assert out["charts"] == []
    assert any("value not in snippet" in i for i in issues)


def test_pipeline_with_mocked_search_and_model(tmp_path, monkeypatch):
    monkeypatch.setenv("FRIDAY_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("friday.config.DATA_DIR", str(tmp_path))
    monkeypatch.setattr("friday.reports.store.DATA_DIR", str(tmp_path))

    src_text = "AlphaCorp grew revenue 12 percent in 2025 according to filings."

    def fake_fetch(query, *, limit=8):
        return [{
            "title": "AlphaCorp filing",
            "url": "https://news.example/alphacorp",
            "snippet": src_text,
        }]

    def fake_query(prompt, **kwargs):
        schema = kwargs.get("format_schema") or {}
        if "sub_questions" in json.dumps(schema):
            return {"message": json.dumps({"sub_questions": [prompt[-40:]]})}
        return {
            "message": json.dumps({
                "summary": {
                    "tldr": "AlphaCorp grew revenue.",
                    "confidence": 0.7,
                    "rationale": "One filing snippet.",
                },
                "findings": [{
                    "id": "f1",
                    "title": "Revenue",
                    "body": "Grew in 2025.",
                    "confidence": 0.7,
                    "source_ids": ["s1"],
                }],
                "claims": [{
                    "id": "c1",
                    "claim": "Revenue grew 12 percent",
                    "source_id": "s1",
                    "evidence": "grew revenue 12 percent in 2025",
                }],
                "charts": [{
                    "id": "ch1",
                    "title": "Growth",
                    "kind": "bar",
                    "series": [{
                        "label": "2025",
                        "value": 12,
                        "source_id": "s1",
                        "snippet": "revenue 12 percent",
                    }],
                }],
                "uncertainties": [],
                "open_questions": [],
                "pros": [],
                "cons": [],
                "next_actions": [{"label": "Save note", "tool": "memory_add", "args": {}}],
            })
        }

    def fake_enrich(row, *, fetch_body=True):
        return {
            "title": row.get("title") or "",
            "url": row.get("url") or "",
            "snippet": row.get("snippet") or "",
            "text": row.get("snippet") or "",
            "image": "",
            "domain": "news.example",
            "kind": "web",
        }

    monkeypatch.setattr("friday.knowledge.search.fetch_web_results", fake_fetch)
    monkeypatch.setattr("friday.models.local.query_model_text", fake_query)
    monkeypatch.setattr("friday.knowledge.enrich.wikipedia_brief", lambda *_a, **_k: None)
    monkeypatch.setattr("friday.knowledge.enrich.duckduckgo_images", lambda *_a, **_k: [])
    monkeypatch.setattr("friday.knowledge.enrich.enrich_source_row", fake_enrich)

    from friday.reports.pipeline import run_research_report

    doc = run_research_report("AlphaCorp revenue research report", mode="quick", save=True)
    assert doc["schema_version"] == "1"
    assert doc["claims"] or doc["findings"]
    assert not doc.get("fallback_plain")
    assert validate_report_schema(doc) == []


def test_adversarial_urls_blocked_in_js_helper():
    """Mirror reports.js safeHttpUrl rules in Python for regression."""
    from urllib.parse import urlparse

    def safe(u: str) -> str | None:
        try:
            x = urlparse(u)
            if x.scheme not in ("http", "https"):
                return None
            return u
        except Exception:
            return None

    assert safe("javascript:alert(1)") is None
    assert safe("data:text/html,hi") is None
    assert safe("https://evil.example/x") is not None


def test_export_html_has_no_script_tags(tmp_path, monkeypatch):
    monkeypatch.setattr("friday.reports.store.DATA_DIR", str(tmp_path))
    from friday.reports.store import export_standalone_html

    doc = _minimal_doc(
        summary={
            "tldr": "<script>alert(1)</script> and [click](javascript:alert(1))",
            "confidence": 0.1,
            "rationale": "xss",
        }
    )
    html = export_standalone_html(doc)
    assert "<script>" not in html.lower().replace("&lt;script&gt;", "")
    assert "javascript:" not in html
    assert "&lt;script&gt;" in html
