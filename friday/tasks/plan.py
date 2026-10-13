"""Persistent day plan — SQLite-backed 'what we're doing today' agenda items."""

from __future__ import annotations

import json
import time
import uuid
from datetime import date
from pathlib import Path
from typing import Any

from friday.config import DATA_DIR, ensure_data_dirs
from friday.store.db import connect, ensure_schema

_migrated = False


def _today() -> str:
    return date.today().isoformat()


def _plan_json_path() -> Path:
    ensure_data_dirs()
    return Path(DATA_DIR) / "today_plan.json"


def _migrate_json_once() -> None:
    """One-shot import from today_plan.json, then rename so we never double-import."""
    global _migrated
    if _migrated:
        return
    path = _plan_json_path()
    if not path.exists():
        _migrated = True
        return
    ensure_schema()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        path.rename(path.with_suffix(".json.bad"))
        _migrated = True
        return
    day = str(data.get("date") or _today())
    items = data.get("items") or []
    with connect() as conn:
        for it in items:
            iid = str(it.get("id") or uuid.uuid4())
            conn.execute(
                """
                INSERT OR IGNORE INTO plan_items (id, day, text, note, done, carried, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    iid,
                    day,
                    str(it.get("text") or "").strip() or "(empty)",
                    str(it.get("note") or ""),
                    1 if it.get("done") else 0,
                    1 if it.get("carried") else 0,
                    float(it.get("created_at") or time.time()),
                ),
            )
        conn.commit()
    try:
        path.rename(path.with_suffix(".json.migrated"))
    except Exception:
        path.unlink(missing_ok=True)
    _migrated = True


def _roll_day(conn) -> None:
    """Carry incomplete items into today; drop completed items from older days."""
    today = _today()
    rows = conn.execute(
        "SELECT id, day, text, note, done, carried, created_at FROM plan_items WHERE day != ?",
        (today,),
    ).fetchall()
    if not rows:
        return
    for r in rows:
        if int(r["done"] or 0):
            conn.execute("DELETE FROM plan_items WHERE id = ?", (r["id"],))
        else:
            conn.execute(
                "UPDATE plan_items SET day = ?, carried = 1 WHERE id = ?",
                (today, r["id"]),
            )
    conn.commit()


def _row_to_item(r: Any) -> dict[str, Any]:
    return {
        "id": r["id"],
        "text": r["text"],
        "note": r["note"] or "",
        "done": bool(r["done"]),
        "carried": bool(r["carried"]),
        "created_at": float(r["created_at"] or 0),
    }


def _load() -> dict[str, Any]:
    _migrate_json_once()
    with connect() as conn:
        _roll_day(conn)
        rows = conn.execute(
            """
            SELECT id, day, text, note, done, carried, created_at
            FROM plan_items WHERE day = ?
            ORDER BY created_at ASC
            """,
            (_today(),),
        ).fetchall()
    return {"date": _today(), "items": [_row_to_item(r) for r in rows]}


def get_plan() -> dict[str, Any]:
    return _load()


def add_item(text: str, *, note: str = "") -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        raise ValueError("text required")
    _migrate_json_once()
    item = {
        "id": str(uuid.uuid4()),
        "text": text,
        "note": (note or "").strip(),
        "done": False,
        "carried": False,
        "created_at": time.time(),
    }
    with connect() as conn:
        _roll_day(conn)
        conn.execute(
            """
            INSERT INTO plan_items (id, day, text, note, done, carried, created_at)
            VALUES (?, ?, ?, ?, 0, 0, ?)
            """,
            (item["id"], _today(), item["text"], item["note"], item["created_at"]),
        )
        conn.commit()
    return item


def set_done(item_id: str, done: bool = True) -> dict[str, Any] | None:
    _migrate_json_once()
    with connect() as conn:
        _roll_day(conn)
        cur = conn.execute(
            "UPDATE plan_items SET done = ? WHERE id = ?",
            (1 if done else 0, item_id),
        )
        conn.commit()
        if cur.rowcount <= 0:
            return None
        row = conn.execute(
            "SELECT id, day, text, note, done, carried, created_at FROM plan_items WHERE id = ?",
            (item_id,),
        ).fetchone()
    return _row_to_item(row) if row else None


def remove_item(item_id: str) -> bool:
    _migrate_json_once()
    with connect() as conn:
        cur = conn.execute("DELETE FROM plan_items WHERE id = ?", (item_id,))
        conn.commit()
        return cur.rowcount > 0


def format_for_prompt() -> str:
    data = _load()
    items = data.get("items") or []
    if not items:
        return "(no agenda items for today)"
    lines = []
    for it in items:
        mark = "[x]" if it.get("done") else "[ ]"
        note = f" — {it['note']}" if it.get("note") else ""
        lines.append(f"{mark} {it.get('text', '')}{note}")
    return "\n".join(lines)


def list_plan_for_overview(limit: int = 100) -> list[dict[str, Any]]:
    """Flat rows for Memory overview (today + carried)."""
    data = _load()
    out = []
    for it in (data.get("items") or [])[:limit]:
        out.append(
            {
                "id": it.get("id", ""),
                "text": ("✓ " if it.get("done") else "") + (it.get("text") or ""),
                "created_at": float(it.get("created_at") or 0),
            }
        )
    return out
