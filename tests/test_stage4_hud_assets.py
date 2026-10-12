"""Static checks for Stage 4 HUD assets (no browser required)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_hud_design_doc_exists():
    p = ROOT / "docs" / "design" / "hud.md"
    assert p.is_file()
    text = p.read_text(encoding="utf-8")
    assert "Arwes" in text
    assert "120" in text and "200" in text


def test_motion_and_sfx_public():
    motion = (ROOT / "web" / "public" / "motion.js").read_text(encoding="utf-8")
    sfx = (ROOT / "web" / "public" / "sfx.js").read_text(encoding="utf-8")
    assert "friday_low_effects" in motion
    assert "prefers-reduced-motion" in motion
    assert "AudioContext" in sfx
    assert "friday_sfx_mute" in sfx


def test_index_wires_stage4_without_cdn_fonts():
    html = (ROOT / "web" / "public" / "index.html").read_text(encoding="utf-8")
    assert "hud.css" in html
    assert "motion.js" in html
    assert "sfx.js" in html
    assert "fonts.googleapis.com" not in html


def test_references_arwes():
    refs = (ROOT / "docs" / "REFERENCES.md").read_text(encoding="utf-8")
    assert "Arwes" in refs
    assert "ideas only" in refs.lower() or "Ideas only" in refs
