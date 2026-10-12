"""Load and validate Friday research report schema v1."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_SCHEMA_PATH = Path(__file__).resolve().parent / "schema" / "report_v1.json"
_schema_cache: dict | None = None


def load_schema() -> dict:
    global _schema_cache
    if _schema_cache is None:
        _schema_cache = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    return _schema_cache


def validate_report_schema(doc: dict[str, Any]) -> list[str]:
    """Return list of schema errors (empty = ok)."""
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        return _light_validate(doc)
    validator = Draft202012Validator(load_schema())
    return sorted(e.message for e in validator.iter_errors(doc))


def _light_validate(doc: dict[str, Any]) -> list[str]:
    errs: list[str] = []
    if doc.get("schema_version") != "1":
        errs.append("schema_version must be '1'")
    for key in ("id", "query", "mode", "created_at", "summary", "sources", "claims", "trace"):
        if key not in doc:
            errs.append(f"missing {key}")
    return errs
