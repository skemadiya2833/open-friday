"""SQLite structured store vs Chroma — plan, facts, calendar cache, memory overview."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest


@pytest.fixture()
def store_dir(tmp_path, monkeypatch):
    db = str(tmp_path / "tasks.sqlite")
    monkeypatch.setattr("friday.config.DATA_DIR", str(tmp_path))
    monkeypatch.setattr("friday.config.TASKS_DB", db)
    monkeypatch.setattr("friday.store.db.TASKS_DB", db)
    monkeypatch.setattr("friday.tasks.plan.DATA_DIR", str(tmp_path))
    import friday.tasks.plan as plan_mod

    plan_mod._migrated = False
    from friday.store.db import ensure_schema

    ensure_schema()
    yield tmp_path
    plan_mod._migrated = False


def test_plan_crud_sqlite(store_dir):
    from friday.tasks import plan as plan_mod

    item = plan_mod.add_item("deep work")
    data = plan_mod.get_plan()
    assert any(it["id"] == item["id"] for it in data["items"])
    assert "deep work" in plan_mod.format_for_prompt()
    assert plan_mod.set_done(item["id"], True)
    assert plan_mod.remove_item(item["id"])
    assert plan_mod.get_plan()["items"] == []


def test_plan_json_migration(store_dir):
    import json
    import time

    from friday.tasks import plan as plan_mod

    path = Path(store_dir) / "today_plan.json"
    path.write_text(
        json.dumps(
            {
                "date": plan_mod._today(),
                "items": [
                    {
                        "id": "legacy-1",
                        "text": "from json",
                        "note": "",
                        "done": False,
                        "created_at": time.time(),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    plan_mod._migrated = False
    data = plan_mod.get_plan()
    assert any(it["text"] == "from json" for it in data["items"])
    assert not path.exists()


def test_owner_facts_sqlite(store_dir):
    from friday.assistant import automemory as AM
    from friday.store.facts import add_fact, list_facts

    add_fact(
        "The owner's name is Ada",
        source="auto",
        kind="fact",
        fact_id="auto-test-ada",
        mirror_chroma=False,
    )
    assert any("Ada" in f for f in list_facts(8))
    assert any("Ada" in f for f in AM.owner_facts(8))


def test_remember_writes_sqlite(store_dir, monkeypatch):
    from friday.assistant import automemory as AM
    from friday.store import facts as facts_mod
    from friday.store.facts import list_facts

    real = facts_mod.add_fact

    def no_chroma(text, **kw):
        kw = dict(kw)
        kw["mirror_chroma"] = False
        return real(text, **kw)

    monkeypatch.setattr(facts_mod, "add_fact", no_chroma)
    found = AM.remember("my name is Zara", background=False)
    assert found
    assert any("Zara" in f for f in list_facts(10))


def test_calendar_cache_upsert_and_read(store_dir):
    from friday.calendar import cache as cal_cache

    now = datetime.now().astimezone().replace(hour=10, minute=0, second=0, microsecond=0)
    events = [
        {
            "uid": "e1",
            "summary": "Standup",
            "start": now,
            "end": now + timedelta(minutes=30),
            "location": "",
            "all_day": False,
        }
    ]
    assert cal_cache.upsert_events(events) == 1
    day_ev = cal_cache.events_for_day()
    assert any(e["summary"] == "Standup" for e in day_ev)
    lines = [f"{e['start'].strftime('%H:%M')} — {e['summary']}" for e in day_ev]
    assert any("Standup" in ln for ln in lines)


def test_memory_overview_excludes_chat(store_dir, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("FRIDAY_AUTH", "off")
    monkeypatch.setenv("FRIDAY_TOASTS", "off")
    from friday.store.facts import add_fact

    add_fact("The owner likes coffee", source="auto", kind="fact", mirror_chroma=False)

    from friday.server.app import app

    with TestClient(app, base_url="http://127.0.0.1:8787") as client:
        res = client.get("/api/memory/overview")
    assert res.status_code == 200, res.text
    data = res.json()
    kinds = {i["kind"] for i in data.get("items") or []}
    assert "chat" not in kinds
    texts = " ".join(i["text"] for i in data.get("items") or [])
    assert "coffee" in texts.lower()
