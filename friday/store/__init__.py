"""Structured local store (SQLite). Vectors stay in Chroma for semantic notes only."""

from friday.store.db import connect, ensure_schema

__all__ = ["connect", "ensure_schema"]
