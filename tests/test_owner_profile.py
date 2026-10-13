"""Owner profile + upgrade capture."""

from __future__ import annotations

import json
from pathlib import Path


def test_owner_profile_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("FRIDAY_DATA_DIR", str(tmp_path))
    # Force config DATA_DIR if already imported
    import friday.config as cfg

    monkeypatch.setattr(cfg, "DATA_DIR", Path(tmp_path))

    from friday.runtime import owner_profile as op

    assert op.load() == {"about": "", "upgrades": []}
    op.update(about="I prefer concise replies.")
    assert op.about_text() == "I prefer concise replies."
    op.add_upgrade("Add calendar week view", source="manual")
    op.add_upgrade("Add calendar week view", source="manual")  # dedupe
    ups = op.upgrade_lines()
    assert ups == ["Add calendar week view"]
    block = op.prompt_block()
    assert "I prefer concise replies" in block
    assert "calendar week view" in block.lower()
    assert "UPGRADE:" in block

    path = Path(tmp_path) / "owner_profile.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["about"].startswith("I prefer")


def test_capture_upgrades_strips_line(tmp_path, monkeypatch):
    monkeypatch.setenv("FRIDAY_DATA_DIR", str(tmp_path))
    import friday.config as cfg

    monkeypatch.setattr(cfg, "DATA_DIR", Path(tmp_path))

    from friday.skills.builtin.chat.handler import _capture_upgrades

    cleaned, captured = _capture_upgrades(
        "Got it.\nUPGRADE: Smoother report exports\nI'll remember that."
    )
    assert "UPGRADE:" not in cleaned
    assert "Got it." in cleaned
    assert captured == ["Smoother report exports"]
    from friday.runtime.owner_profile import upgrade_lines

    assert "Smoother report exports" in upgrade_lines()
