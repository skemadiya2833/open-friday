"""Fine-tune corpus: turns, ratings, daily export."""

from __future__ import annotations

from pathlib import Path

import pytest

from friday.runtime import training_log as T


@pytest.fixture()
def training_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "training"
    monkeypatch.setattr("friday.config.TRAINING_DIR", str(root))
    return root


def test_log_and_rate_and_export(training_dir: Path):
    tid = T.log_training_turn(
        user="research brand setup",
        reply="Top hits: BrandBible; USPTO trademarks.",
        skill="research",
        intent={"mode": "research", "skill_id": "research"},
        session_id="sess-1",
        meta={"tools": [{"tool": "web_search"}]},
    )
    assert tid
    assert (training_dir / "turns").exists()

    rated = T.rate_turn(tid, "up", note="solid titles")
    assert rated["ok"] is True

    rows = T.list_day()
    assert len(rows) == 1
    assert rows[0]["label"] == "good"
    assert rows[0]["user"] == "research brand setup"

    summary = T.day_summary()
    assert summary["turns"] == 1
    assert summary["good"] == 1
    assert summary["bad"] == 0

    path = T.export_day(labeled_only=True)
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "conversations" in text
    assert "BrandBible" in text
    assert '"label": "good"' in text


def test_auto_flags_glitch(training_dir: Path):
    tid = T.log_training_turn(
        user="hello",
        reply="I glitched on that, boss. Say it once more?",
        skill="chat",
    )
    rows = {r["turn_id"]: r for r in T.list_day()}
    assert "glitch_fallback" in rows[tid]["auto_flags"]


def test_bad_rating_overrides(training_dir: Path):
    tid = T.log_training_turn(user="x", reply="y", skill="chat")
    T.rate_turn(tid, "good")
    T.rate_turn(tid, "bad")
    rows = T.list_day()
    assert rows[0]["label"] == "bad"
