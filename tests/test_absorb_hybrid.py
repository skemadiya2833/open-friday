"""Hybrid absorb: secret prefs, plans, skill fetch gate, telegram allow-list."""

from __future__ import annotations

import friday.runtime.prefs as prefs


def test_secret_pref_masked_in_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(prefs, "_path", lambda: tmp_path / "runtime_prefs.json")
    prefs.clear_cache()
    prefs.update({"telegram_bot_token": "123456:ABC-SECRET-TOKEN"})
    snap = prefs.snapshot()
    item = next(x for x in snap["items"] if x["key"] == "telegram_bot_token")
    assert item["secret"] is True
    assert item["has_secret"] is True
    assert item["value"] == prefs.SECRET_MASK
    assert "ABC-SECRET" not in str(item["value"])
    # plaintext still available via get() for the channel runtime
    assert prefs.get("telegram_bot_token") == "123456:ABC-SECRET-TOKEN"


def test_secret_keep_sentinel(tmp_path, monkeypatch):
    monkeypatch.setattr(prefs, "_path", lambda: tmp_path / "runtime_prefs.json")
    prefs.clear_cache()
    prefs.update({"telegram_bot_token": "keep-me"})
    prefs.update({"telegram_bot_token": prefs.SECRET_KEEP})
    assert prefs.get("telegram_bot_token") == "keep-me"
    prefs.update({"telegram_bot_token": prefs.SECRET_MASK})
    assert prefs.get("telegram_bot_token") == "keep-me"
    prefs.update({"telegram_bot_token": ""})
    assert prefs.get("telegram_bot_token") == ""


def test_channels_group_in_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(prefs, "_path", lambda: tmp_path / "runtime_prefs.json")
    prefs.clear_cache()
    snap = prefs.snapshot()
    gids = [g["id"] for g in snap["groups"]]
    assert "channels" in gids
    keys = {i["key"] for i in snap["items"]}
    assert {"telegram_enabled", "cua_enabled", "skill_hub_fetch", "presence_orb"} <= keys


def test_plan_create_approve_rerun(tmp_path, monkeypatch):
    from friday.plans.store import PlanStore

    store = PlanStore(tmp_path / "plans")
    plan = store.create("Test build", ["step one", "step two"], kind="desktop")
    assert plan["status"] == "draft"
    assert plan["version"] == 1
    approved = store.approve(plan["id"])
    assert approved["status"] == "approved"
    clone = store.rerun(plan["id"])
    assert clone["version"] == 2
    assert clone["status"] == "draft"
    assert clone["id"] != plan["id"]
    assert plan["id"] in clone["lineage"]


def test_skill_fetch_requires_pref(tmp_path, monkeypatch):
    from friday.skills.agentskills import SkillError, SkillStore, set_store

    monkeypatch.setattr(prefs, "_path", lambda: tmp_path / "runtime_prefs.json")
    prefs.clear_cache()
    prefs.update({"skill_hub_fetch": False})
    store = SkillStore(tmp_path / "skills_md")
    set_store(store)
    try:
        try:
            store.fetch_into_inbox("https://example.com/SKILL.md")
            raise AssertionError("expected SkillError")
        except SkillError as exc:
            assert "off" in str(exc).lower() or "fetch" in str(exc).lower()
    finally:
        set_store(None)


def test_mcp_yaml_has_cua():
    from pathlib import Path

    import yaml

    p = Path(__file__).resolve().parents[1] / "config" / "mcp_servers.yaml"
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert "cua" in raw["servers"]
    assert raw["servers"]["cua"]["enabled"] is False


def test_telegram_status_idle(monkeypatch, tmp_path):
    monkeypatch.setattr(prefs, "_path", lambda: tmp_path / "runtime_prefs.json")
    prefs.clear_cache()
    from friday.channels import telegram as tg

    tg.stop()
    st = tg.sync_from_prefs()
    assert st["running"] is False
