"""CAD prefs, detect, and Systems-configurable settings."""

from __future__ import annotations

from pathlib import Path

import friday.runtime.prefs as prefs


def test_cad_keys_in_schema():
    for key in (
        "cad_enabled",
        "freecad_install",
        "freecad_s1_repo",
        "freecad_s1_python",
        "freecad_s1_model",
        "freecad_s1_port",
    ):
        assert key in prefs.SCHEMA
        assert prefs.SCHEMA[key]["group"] == "cad"
    assert any(g[0] == "cad" for g in prefs._GROUPS)


def test_cad_prefs_update_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(prefs, "_path", lambda: tmp_path / "runtime_prefs.json")
    prefs.clear_cache()
    prefs.update({
        "cad_enabled": True,
        "freecad_install": r"C:\Program Files\FreeCAD 1.1",
        "freecad_s1_port": 8765,
    })
    assert prefs.get("cad_enabled") is True
    assert prefs.get("freecad_install").endswith("FreeCAD 1.1")
    assert prefs.get("freecad_s1_port") == 8765
    assert prefs.source_of("cad_enabled") == "ui"


def test_resolve_uses_prefs(tmp_path, monkeypatch):
    monkeypatch.setattr(prefs, "_path", lambda: tmp_path / "runtime_prefs.json")
    prefs.clear_cache()
    prefs.update({
        "cad_enabled": True,
        "freecad_install": r"C:\Program Files\FreeCAD 1.1",
        "freecad_s1_repo": str(tmp_path / "biome-s1"),
        "freecad_s1_python": str(tmp_path / "python.exe"),
        "freecad_s1_model": "shhivv/taiga-s1",
        "freecad_s1_port": 9001,
    })
    from friday.cad.settings import resolve

    cfg = resolve()
    assert cfg.enabled is True
    assert cfg.s1_port == 9001
    assert "FreeCAD 1.1" in cfg.freecad_install


def test_parse_path_from_message():
    from friday.cad.settings import parse_path_from_message

    got = parse_path_from_message(r"FreeCAD is at C:\Program Files\FreeCAD 1.1")
    assert got and got.endswith("FreeCAD 1.1")


def test_detect_freecad_finds_program_files():
    from friday.cad.settings import detect_freecad_installs

    found = detect_freecad_installs()
    # Machine under test has FreeCAD 1.1 — soft assert if present
    if Path(r"C:\Program Files\FreeCAD 1.1\bin\freecad.exe").is_file():
        assert any("FreeCAD 1.1" in str(p) for p in found)


def test_prefs_update_tool(tmp_path, monkeypatch):
    monkeypatch.setattr(prefs, "_path", lambda: tmp_path / "runtime_prefs.json")
    prefs.clear_cache()
    from friday.tools.builtin import _prefs_update

    res = _prefs_update({"key": "cad_enabled", "value": True})
    assert not res.is_error
    assert prefs.get("cad_enabled") is True


def test_intent_setup_cad():
    from friday.assistant import intent as intent_mod

    got = intent_mod._deterministic_intent("set up CAD")
    assert got and got.skill_id == "cad"
