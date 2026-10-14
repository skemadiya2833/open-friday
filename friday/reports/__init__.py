"""Structured research reports (schema v1).

Lazy exports — eager imports here caused circular deadlocks under concurrent
``/api/reports/start`` (pipeline ↔ store via package ``__init__``).
"""

from __future__ import annotations

from typing import Any

__all__ = ["run_research_report", "list_reports", "get_report", "delete_report"]


def __getattr__(name: str) -> Any:
    if name == "run_research_report":
        from friday.reports.pipeline import run_research_report

        return run_research_report
    if name in {"list_reports", "get_report", "delete_report", "save_report"}:
        from friday.reports import store as _store

        return getattr(_store, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
