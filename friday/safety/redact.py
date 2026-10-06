"""Secret redaction for logs and audit records."""

from __future__ import annotations

import re
from typing import Any

REDACTED = "[REDACTED]"

_SENSITIVE_KEY = re.compile(
    r"(pass(word|wd)?|secret|token|api[-_]?key|authorization|auth|cookie|session|private[-_]?key|credential|bearer)",
    re.IGNORECASE,
)

_VALUE_PATTERNS = [
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-+/=]{8,}"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"),            # OpenAI-style
    re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}"),           # Google API keys
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),        # GitHub tokens
    re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}"),     # Slack tokens
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
    re.compile(r"(?i)(password|passwd|pwd|secret|token|api[_-]?key)\s*[=:]\s*[^\s\"']+"),
]


def redact_text(text: str) -> str:
    out = text
    for pat in _VALUE_PATTERNS:
        out = pat.sub(REDACTED, out)
    return out


def redact(value: Any, *, max_str: int = 2000) -> Any:
    """Return a JSON-safe, secret-free, size-bounded copy of ``value``."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        text = redact_text(value)
        if len(text) > max_str:
            text = text[:max_str] + f"...[+{len(text) - max_str} chars]"
        return text
    if isinstance(value, bytes):
        return f"<{len(value)} bytes>"
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for k, v in value.items():
            key = str(k)
            clean[key] = REDACTED if _SENSITIVE_KEY.search(key) else redact(v, max_str=max_str)
        return clean
    if isinstance(value, (list, tuple, set)):
        return [redact(v, max_str=max_str) for v in list(value)[:100]]
    return redact(str(value), max_str=max_str)
