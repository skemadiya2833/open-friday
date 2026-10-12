"""Reject model commentary that cites numbers not present in computed metrics."""

from __future__ import annotations

import json
import re
from typing import Any

_NUM = re.compile(r"(?<![A-Za-z0-9_])-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?(?![A-Za-z0-9_])")


def _collect_numbers(obj: Any) -> set[str]:
    found: set[str] = set()

    def walk(x: Any) -> None:
        if isinstance(x, bool):
            return
        if isinstance(x, (int, float)):
            found.add(_normalize_num(x))
            return
        if isinstance(x, str):
            for m in _NUM.finditer(x):
                found.add(_normalize_token(m.group(0)))
            return
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(obj)
    return found


def _normalize_num(n: float | int) -> str:
    if isinstance(n, float) and n.is_integer():
        return str(int(n))
    s = str(n)
    if "." in s:
        s = s.rstrip("0").rstrip(".") or "0"
    return s


def _normalize_token(tok: str) -> str:
    t = tok.strip()
    if t.startswith("+"):
        t = t[1:]
    if "." in t:
        t = t.rstrip("0").rstrip(".") or "0"
    return t


def tokenize_numeric_literals(text: str) -> list[str]:
    return [_normalize_token(m.group(0)) for m in _NUM.finditer(text or "")]


def validate_commentary(commentary: str, metrics_payload: dict[str, Any]) -> tuple[bool, list[str]]:
    """Return (ok, list of invented numbers)."""
    allowed = _collect_numbers(metrics_payload)
    # Also allow numbers embedded in chart series inside the same payload tree
    invented: list[str] = []
    for tok in tokenize_numeric_literals(commentary):
        if tok in allowed:
            continue
        # Percent display: 42% may refer to 0.42 ratio
        if tok.endswith("%"):
            continue
        invented.append(tok)
    return (len(invented) == 0, invented)


def metrics_json_for_guard(metrics: dict[str, Any]) -> dict[str, Any]:
    """Stable JSON-friendly blob used for guard comparisons."""
    return json.loads(json.dumps(metrics))
