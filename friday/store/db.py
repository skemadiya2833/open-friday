"""Shared SQLite connection for plan, facts, calendar cache, and (via TASKS_DB) jobs."""

from __future__ import annotations

import sqlite3
import threading

from friday.config import TASKS_DB, ensure_data_dirs

_lock = threading.Lock()
_schema_ready = False


def connect() -> sqlite3.Connection:
    ensure_data_dirs()
    conn = sqlite3.connect(TASKS_DB, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    ensure_schema(conn)
    return conn


def ensure_schema(conn: sqlite3.Connection | None = None) -> None:
    """Idempotent DDL for structured Friday data (jobs table owned by TaskScheduler too)."""
    global _schema_ready
    owns = conn is None
    if owns:
        ensure_data_dirs()
        conn = sqlite3.connect(TASKS_DB, check_same_thread=False)
        conn.row_factory = sqlite3.Row
    assert conn is not None
    with _lock:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                title TEXT,
                prompt TEXT,
                skill_id TEXT,
                status TEXT,
                cron TEXT,
                run_at REAL,
                created_at REAL,
                last_run REAL,
                meta TEXT
            );
            CREATE TABLE IF NOT EXISTS plan_items (
                id TEXT PRIMARY KEY,
                day TEXT NOT NULL,
                text TEXT NOT NULL,
                note TEXT DEFAULT '',
                done INTEGER DEFAULT 0,
                carried INTEGER DEFAULT 0,
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_plan_items_day ON plan_items(day);
            CREATE TABLE IF NOT EXISTS owner_facts (
                id TEXT PRIMARY KEY,
                text TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'manual',
                kind TEXT NOT NULL DEFAULT 'fact',
                created_at REAL NOT NULL,
                chroma_id TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_owner_facts_created ON owner_facts(created_at DESC);
            CREATE TABLE IF NOT EXISTS calendar_events (
                uid TEXT NOT NULL,
                start_ts REAL NOT NULL,
                end_ts REAL NOT NULL,
                summary TEXT,
                location TEXT,
                all_day INTEGER DEFAULT 0,
                raw_day TEXT,
                updated_at REAL NOT NULL,
                PRIMARY KEY (uid, start_ts)
            );
            CREATE INDEX IF NOT EXISTS idx_calendar_events_day ON calendar_events(raw_day);
            CREATE INDEX IF NOT EXISTS idx_calendar_events_start ON calendar_events(start_ts);
            """
        )
        conn.commit()
        _schema_ready = True
    if owns:
        conn.close()
