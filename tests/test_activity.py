"""Activity awareness, metrics, commentary guard."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch


from friday.activity.aw import ActivityWatchClient, approve_rules, suggest_categorization_rules
from friday.activity import local_logger
from friday.activity.metrics import compute_metrics
from friday.reports.commentary_guard import validate_commentary
from friday.reports.productivity import build_productivity_report


def test_aw_unavailable_when_info_fails():
    client = ActivityWatchClient()
    with patch.object(client, "_get_json", side_effect=OSError("connection refused")):
        st = client.probe()
    assert st["available"] is False
    assert client.list_buckets()["available"] is False
    assert client.fetch_window_events(
        start=datetime.now(timezone.utc),
        end=datetime.now(timezone.utc),
    ) == []


def test_local_logger_requires_consent(monkeypatch, tmp_path):
    monkeypatch.setattr("friday.config.DATA_DIR", str(tmp_path))
    monkeypatch.setattr("friday.activity.local_logger.DATA_DIR", str(tmp_path))
    assert local_logger.consent_enabled() is False
    assert local_logger.sample_once() is None
    local_logger.set_consent(True)
    assert local_logger.consent_enabled() is True
    with patch("friday.activity.local_logger._foreground_win32", return_value=("1Password.exe", "Vault")):
        assert local_logger.sample_once() is None
    deleted = local_logger.delete_all()
    assert deleted["deleted"]["consent"] or deleted["deleted"]["log"]
    assert local_logger.consent_enabled() is False


def test_metrics_from_fixture_events():
    events = [
        {"start": 1000, "duration": 3600, "app": "code.exe", "category": "deep_work"},
        {"start": 5000, "duration": 1800, "app": "zoom.exe", "category": "communication"},
        {"start": 7000, "duration": 2000, "app": "code.exe", "category": "deep_work"},
    ]
    m = compute_metrics(events)
    assert m["active_seconds"] == 7400
    assert m["deep_work_seconds"] == 5600
    assert m["meeting_seconds"] == 1800
    assert m["deep_work_ratio"] == round(5600 / 7400, 4)
    assert m["focus_block_count"] >= 1


def test_commentary_guard_rejects_invented_numbers():
    metrics = {"active_seconds": 3600, "deep_work_ratio": 0.42}
    ok, bad = validate_commentary("You worked 3600 seconds but also hit 99% efficiency.", metrics)
    assert ok is False
    assert "99" in bad
    ok2, bad2 = validate_commentary("Active time was 3600 seconds; ratio 0.42.", metrics)
    assert ok2 is True
    assert bad2 == []


def test_suggest_and_approve_rules(tmp_path, monkeypatch):
    monkeypatch.setattr("friday.config.DATA_DIR", str(tmp_path))
    raw = [{"data": {"app": "Cursor.exe", "title": "Cursor — friday"}, "timestamp": 1, "duration": 10}] * 5
    sug = suggest_categorization_rules(raw, limit=3)
    assert sug
    approved = approve_rules(sug)
    assert any(r.get("approved") for r in approved)


def test_productivity_report_commentary_flag():
    metrics = compute_metrics(
        [{"start": 0, "duration": 100, "app": "a", "category": "deep_work"}],
    )
    doc = build_productivity_report(metrics, commentary="Totally 5000 hours.", events=[])
    assert doc["commentary_valid"] is False
