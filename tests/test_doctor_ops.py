"""Stage 5: doctor and ops summary."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from friday.diagnostics.doctor import print_doctor_report, run_doctor
from friday.diagnostics.ops_summary import ops_summary


def test_run_doctor_never_raises(monkeypatch):
    monkeypatch.setenv("FRIDAY_AUTH", "local")
    monkeypatch.setenv("FRIDAY_HOST", "127.0.0.1")
    report = run_doctor(probe_hardware=False)
    assert "checks" in report
    assert "next_steps" in report
    assert isinstance(report["next_steps"], list)
    assert any(c["id"] == "config" for c in report["checks"])
    assert any(c["id"] == "models" for c in report["checks"])
    assert any(c["id"] == "python" for c in report["checks"])
    assert any(c["id"] == "imports" for c in report["checks"])
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
            return json.dumps(
                {
                    "models": [
                        {"name": "qwen3.5:9b"},
                        {"name": "nomic-embed-text:latest"},
                        {"name": "qwen3-vl:8b-instruct"},
                    ]
                }
            ).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    with patch("urllib.request.urlopen", return_value=FakeResp()):
        report = run_doctor(probe_hardware=False)
    models = next(c for c in report["checks"] if c["id"] == "models")
    assert models["status"] in ("pass", "warn")
    assert report["next_steps"]


def test_doctor_next_steps_include_pull_when_models_missing(monkeypatch):
    monkeypatch.setenv("FRIDAY_AUTH", "local")

    class FakeResp:
        def read(self):
            return json.dumps({"models": []}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    with patch("urllib.request.urlopen", return_value=FakeResp()):
        report = run_doctor(probe_hardware=False)
    assert any(s.startswith("ollama pull ") for s in report["next_steps"])


def test_print_doctor_report_exit_codes(monkeypatch, capsys):
    monkeypatch.setenv("FRIDAY_AUTH", "local")
    report = {
        "status": "pass",
        "version": "3.0.0",
        "checks": [{"id": "python", "status": "pass", "message": "ok", "detail": {}}],
        "next_steps": ["Start Friday: friday"],
    }
    assert print_doctor_report(report) == 0
    out = capsys.readouterr().out
    assert "PASS" in out
    assert "next steps" in out.lower()


def test_cli_doctor_json(monkeypatch):
    from friday.cli import main

    monkeypatch.setenv("FRIDAY_AUTH", "local")
    with patch("friday.diagnostics.doctor.run_doctor") as rd:
        rd.return_value = {
            "ok": True,
            "status": "pass",
            "version": "3.0.0",
            "checks": [],
            "next_steps": [],
            "hardware": {},
        }
        with pytest.raises(SystemExit) as ei:
            main(["doctor", "--json", "--no-hardware"])
        assert ei.value.code == 0
