"""Stage 5: doctor and ops summary."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from friday.diagnostics.doctor import run_doctor
from friday.diagnostics.ops_summary import ops_summary


def test_run_doctor_never_raises(monkeypatch):
    monkeypatch.setenv("FRIDAY_AUTH", "local")
    monkeypatch.setenv("FRIDAY_HOST", "127.0.0.1")
    report = run_doctor(probe_hardware=False)
    assert "checks" in report
    assert any(c["id"] == "config" for c in report["checks"])
    assert any(c["id"] == "models" for c in report["checks"])
    detail = next(c["detail"] for c in report["checks"] if c["id"] == "models")
    assert "pull_hint" in detail
    assert "never downloads" in detail["pull_hint"].lower()


def test_ops_summary_shape(monkeypatch, tmp_path):
    monkeypatch.setenv("FRIDAY_DATA_DIR", str(tmp_path))
    out = ops_summary()
    assert "counts" in out
    assert "health" in out
    assert "duration_ms" in out
    assert out["duration_ms"] >= 0


def test_doctor_ollama_tags_mock(monkeypatch):
    monkeypatch.setenv("FRIDAY_AUTH", "local")

    class FakeResp:
        def read(self):
            return json.dumps({"models": [{"name": "qwen3.5:9b"}, {"name": "nomic-embed-text:latest"}]}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    with patch("urllib.request.urlopen", return_value=FakeResp()):
        report = run_doctor(probe_hardware=False)
    models = next(c for c in report["checks"] if c["id"] == "models")
    assert models["status"] in ("pass", "warn")
