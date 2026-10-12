"""Shared helpers for owner-only built-in scheduler jobs."""

from __future__ import annotations

import json
import time
from typing import Any, Callable


def sync_job(
    *,
    job_id: str,
    enabled: bool,
    cron: str,
    title: str,
    prompt: str,
    skill_id: str,
) -> None:
    from friday.tasks.scheduler import get_scheduler

    sch = get_scheduler()
    try:
        sch.cancel(job_id)
    except Exception:  # noqa: BLE001
        pass
    if not enabled:
        return
    ts = time.time()
    meta = json.dumps({"builtin": True, "agent_schedulable": False})
    with sch._lock, sch._conn() as conn:  # noqa: SLF001
        conn.execute("DELETE FROM jobs WHERE id=?", (job_id,))
        conn.execute(
            "INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?)",
            (job_id, title, prompt, skill_id, "scheduled", cron, None, ts, None, meta),
        )
        conn.commit()
    job = {
        "id": job_id,
        "title": title,
        "prompt": prompt,
        "skill_id": skill_id,
        "status": "scheduled",
        "cron": cron,
        "run_at": None,
        "created_at": ts,
        "last_run": None,
        "meta": {"builtin": True},
    }
    sch._arm(job)  # noqa: SLF001


def settings_io(
    path_fn: Callable[[], Any],
    defaults: dict[str, Any],
) -> tuple[Callable[[], dict[str, Any]], Callable[[dict[str, Any]], None]]:
    import json

    def load() -> dict[str, Any]:
        path = path_fn()
        if not path.exists():
            return dict(defaults)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return dict(defaults)
        out = dict(defaults)
        out.update(data)
        return out

    def save(data: dict[str, Any]) -> None:
        from friday.atomic import write_text_atomic

        write_text_atomic(path_fn(), json.dumps(data, indent=2))

    return load, save
