"""Local task scheduler (APScheduler + SQLite metadata)."""

from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from datetime import datetime
from typing import Any

from friday.config import TASKS_DB, ensure_data_dirs


class TaskScheduler:
    def __init__(self) -> None:
        ensure_data_dirs()
        self._lock = threading.Lock()
        self._scheduler = None
        self._init_db()
        self._start_scheduler()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(TASKS_DB, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute(
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
                )
                """
            )
            conn.commit()

    def _start_scheduler(self) -> None:
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from apscheduler.triggers.cron import CronTrigger  # noqa: F401
            from apscheduler.triggers.date import DateTrigger  # noqa: F401
        except ImportError:
            print("[Tasks] APScheduler not installed — scheduling disabled until deps install.")
            return

        self._scheduler = BackgroundScheduler()
        self._scheduler.start()
        # Restore pending jobs
        now = time.time()
        for job in self.list_jobs():
            if job["status"] not in ("scheduled", "paused"):
                continue
            # a one-shot reminder that came due while Friday was not running: deliver it now, flagged as late
            if job.get("run_at") and not job.get("cron") and float(job["run_at"]) < now and not job.get("last_run") and job["status"] == "scheduled":
                late = int((now - float(job["run_at"])) // 60)
                threading.Timer(3.0, self._execute, args=(job["id"], f"missed {late} min ago" if late else "")).start()
                continue
            self._arm(job)

    def _arm(self, job: dict[str, Any]) -> None:
        if self._scheduler is None:
            return
        from apscheduler.triggers.cron import CronTrigger
        from apscheduler.triggers.date import DateTrigger

        jid = job["id"]

        def _fire() -> None:
            self._execute(jid)

        try:
            self._scheduler.remove_job(jid)
        except Exception:
            pass

        if job.get("cron"):
            self._scheduler.add_job(_fire, CronTrigger.from_crontab(job["cron"]), id=jid, replace_existing=True)
        elif job.get("run_at"):
            when = datetime.fromtimestamp(float(job["run_at"]))
            if when > datetime.now():
                self._scheduler.add_job(_fire, DateTrigger(run_date=when), id=jid, replace_existing=True)

    def add_job(
        self,
        *,
        prompt: str,
        skill_id: str = "chat",
        delay_seconds: float | int | None = None,
        run_at: str | float | None = None,
        cron: str | None = None,
        title: str = "Friday task",
    ) -> dict[str, Any]:
        prompt = (prompt or "").strip()
        if not prompt:
            raise ValueError("prompt required")
        jid = str(uuid.uuid4())
        ts = time.time()
        run_ts: float | None = None
        if delay_seconds is not None:
            run_ts = ts + float(delay_seconds)
        elif run_at is not None:
            if isinstance(run_at, (int, float)):
                run_ts = float(run_at)
            else:
                run_ts = datetime.fromisoformat(str(run_at).replace("Z", "")).timestamp()

        job = {
            "id": jid,
            "title": title,
            "prompt": prompt,
            "skill_id": skill_id,
            "status": "scheduled",
            "cron": cron,
            "run_at": run_ts,
            "created_at": ts,
            "last_run": None,
            "meta": {},
        }
        with self._lock, self._conn() as conn:
            conn.execute(
                "INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    jid, title, prompt, skill_id, "scheduled", cron, run_ts, ts, None, "{}",
                ),
            )
            conn.commit()
        self._arm(job)
        return job

    def list_jobs(self) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]

    def cancel(self, job_id: str) -> bool:
        with self._lock, self._conn() as conn:
            cur = conn.execute("UPDATE jobs SET status=? WHERE id=?", ("cancelled", job_id))
            conn.commit()
            if cur.rowcount == 0:
                return False
        if self._scheduler is not None:
            try:
                self._scheduler.remove_job(job_id)
            except Exception:
                pass
        return True

    def pause(self, job_id: str) -> bool:
        with self._lock, self._conn() as conn:
            cur = conn.execute("UPDATE jobs SET status=? WHERE id=?", ("paused", job_id))
            conn.commit()
            ok = cur.rowcount > 0
        if ok and self._scheduler is not None:
            try:
                self._scheduler.pause_job(job_id)
            except Exception:
                pass
        return ok

    def run_now(self, job_id: str) -> bool:
        jobs = {j["id"]: j for j in self.list_jobs()}
        if job_id not in jobs:
            return False
        threading.Thread(target=self._execute, args=(job_id,), daemon=True).start()
        return True

    def _execute(self, job_id: str, note: str = "") -> None:
        jobs = {j["id"]: j for j in self.list_jobs()}
        job = jobs.get(job_id)
        if not job or job["status"] == "cancelled":
            return
        print(f"[Tasks] Firing {job_id}: {job['title']}")
        with self._conn() as conn:
            conn.execute(
                "UPDATE jobs SET last_run=?, status=? WHERE id=?",
                (time.time(), "running", job_id),
            )
            conn.commit()
        try:
            from friday.tasks import reminders as RM

            if (job.get("skill_id") or "") == "reminder":
                RM.add_notification(job["prompt"], note, job_id=job_id, kind="reminder")
            else:
                from friday.assistant.orchestrator import handle_message

                out = handle_message(job["prompt"], session_id=f"task:{job_id}", skill_override=job.get("skill_id") or None)
                RM.add_notification(job["title"] or "Task finished", str(out.get("reply", ""))[:600], job_id=job_id, kind="task")
            status = "scheduled" if job.get("cron") else "done"
        except Exception as exc:
            print(f"[Tasks] Job failed: {exc}")
            status = "failed"
            try:
                from friday.tasks import reminders as RM

                RM.add_notification(f"Task failed: {job['title']}", str(exc)[:300], job_id=job_id, kind="task")
            except Exception:  # noqa: BLE001
                pass
        with self._conn() as conn:
            conn.execute("UPDATE jobs SET status=? WHERE id=?", (status, job_id))
            conn.commit()

    def shutdown(self) -> None:
        if self._scheduler is None:
            return
        try:
            self._scheduler.shutdown(wait=False)
        except Exception:  # noqa: BLE001
            pass
        self._scheduler = None


_sched: TaskScheduler | None = None


def get_scheduler() -> TaskScheduler:
    global _sched
    if _sched is None:
        _sched = TaskScheduler()
    return _sched
