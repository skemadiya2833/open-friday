# Copyright 2025 The OpenJarvis Authors
# Licensed under the Apache License, Version 2.0
# Source: open-jarvis/OpenJarvis src/openjarvis/skills/security.py
#         (+ importer.py trust/scan ideas)
# Commit: f9e9d5d28d9e58d7fe601c331fc15a02fad32b2c
# Changes for Friday: no community registry bulk-import; trust tiers for
# owner inbox → quarantine → hash-bound install; dangerous capability flags
# from allowed-tools / scripts presence.

"""Skill import security — trust tiers and dangerous capability flags."""

from __future__ import annotations

from enum import Enum
from typing import Iterable


DANGEROUS_CAPABILITIES: frozenset[str] = frozenset(
    {
        "shell:execute",
        "network:listen",
        "filesystem:write",
        "run_shell",
        "powershell",
        "cmd",
    }
)


class TrustTier(str, Enum):
    BUNDLED = "bundled"
    WORKSPACE = "workspace"
    INDEXED = "indexed"
    UNREVIEWED = "unreviewed"


def classify_trust_tier(
    *,
    is_bundled: bool = False,
    is_workspace: bool = False,
    has_signature: bool = False,
    in_index: bool = False,
) -> TrustTier:
    """Provenance tier. External imports are always UNREVIEWED until owner-approved."""
    if is_bundled:
        return TrustTier.BUNDLED
    if is_workspace:
        return TrustTier.WORKSPACE
    if has_signature and in_index:
        return TrustTier.INDEXED
    return TrustTier.UNREVIEWED


def dangerous_from_tools(tools: Iterable[str]) -> list[str]:
    found: list[str] = []
    for t in tools or []:
        key = str(t).strip().lower()
        if key in DANGEROUS_CAPABILITIES or any(d in key for d in ("shell", "powershell", "cmd.exe")):
            found.append(str(t))
    return sorted(set(found))


def enrich_review(report: dict, *, origin: str = "inbox") -> dict:
    """Attach trust-tier + dangerous flags to an agentskills review report."""
    tools = list(report.get("requests_tools") or [])
    danger = dangerous_from_tools(tools)
    if report.get("runs_code"):
        danger = sorted(set(danger + ["scripts:present"]))
    tier = classify_trust_tier(
        is_bundled=origin == "bundled",
        is_workspace=origin == "workspace",
    )
    report = dict(report)
    report["trust_tier"] = tier.value
    report["dangerous_capabilities"] = danger
    report["requires_owner_approval"] = True
    report["auto_enable"] = False
    report["notes"] = list(report.get("notes") or []) + [
        "Import only on explicit owner command; never auto-enable.",
        "Trust is bound to content hash after approve.",
    ]
    return report
