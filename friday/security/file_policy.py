# Copyright 2025 The OpenJarvis Authors
# Licensed under the Apache License, Version 2.0
# Source: open-jarvis/OpenJarvis src/openjarvis/security/file_policy.py
# Commit: f9e9d5d28d9e58d7fe601c331fc15a02fad32b2c
# Changes for Friday: pure-Python fnmatch only; no Rust.

"""Sensitive-file policy for file tools and memory ingest."""

from __future__ import annotations

import fnmatch
from pathlib import Path

DEFAULT_SENSITIVE_PATTERNS: frozenset[str] = frozenset(
    {
        ".env",
        ".env.*",
        "*.env",
        ".secret",
        "*.secrets",
        "credentials.*",
        "*.pem",
        "*.key",
        "*.p12",
        "*.pfx",
        "*.jks",
        "id_rsa",
        "id_ed25519",
        ".htpasswd",
        ".pgpass",
        ".netrc",
        "devices.json",
        "*credentials*.json",
    }
)


def is_sensitive_file(path: str | Path) -> bool:
    p = Path(path)
    name = p.name
    for pattern in DEFAULT_SENSITIVE_PATTERNS:
        if fnmatch.fnmatch(name, pattern):
            return True
    # Walk symlink chain names
    candidate = p
    for _ in range(20):
        try:
            target = candidate.readlink()
        except OSError:
            break
        candidate = target if target.is_absolute() else candidate.parent / target
        for pattern in DEFAULT_SENSITIVE_PATTERNS:
            if fnmatch.fnmatch(candidate.name, pattern):
                return True
    return False
