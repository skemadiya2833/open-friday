# Copyright 2025 The OpenJarvis Authors
# Licensed under the Apache License, Version 2.0
# Source: open-jarvis/OpenJarvis src/openjarvis/security/scanner.py,
#         injection_scanner.py, credential_stripper.py
# Commit: f9e9d5d28d9e58d7fe601c331fc15a02fad32b2c
# Changes for Friday: pure-Python regex scanners; Mode warn|redact|block;
# findings recorded on Friday's hash-chained audit log (no SQLite).

"""Secret / PII / injection scanners with warn, redact, and block modes."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable


class Mode(str, Enum):
    WARN = "warn"
    REDACT = "redact"
    BLOCK = "block"


@dataclass
class Finding:
    kind: str
    label: str
    severity: str  # low|medium|high|critical
    matched: str = ""


@dataclass
class ScanReport:
    findings: list[Finding] = field(default_factory=list)
    text: str = ""
    blocked: bool = False

    @property
    def hit(self) -> bool:
        return bool(self.findings)


_SECRET_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    ("openai_key", re.compile(r"sk-[A-Za-z0-9_-]{20,}"), "critical"),
    ("anthropic_key", re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"), "critical"),
    ("aws_access_key", re.compile(r"AKIA[0-9A-Z]{16}"), "critical"),
    ("github_token", re.compile(r"(?:ghp|gho|ghs|ghr|github_pat)_[A-Za-z0-9_]{36,}"), "critical"),
    ("slack_token", re.compile(r"xox[bpors]-[A-Za-z0-9\-]{10,}"), "high"),
    ("stripe_key", re.compile(r"(?:sk|pk)_(?:test|live)_[A-Za-z0-9]{20,}"), "critical"),
    ("private_key", re.compile(r"-----BEGIN (?:RSA )?PRIVATE KEY-----"), "critical"),
    ("generic_api_key", re.compile(r"""(?:api[_-]?key|secret[_-]?key|auth[_-]?token)\s*[=:]\s*['\"]([^'\"]{8,})['\"]""", re.I), "high"),
    ("password_assignment", re.compile(r"""(?:password|passwd|pwd)\s*[=:]\s*['\"]([^'\"]{4,})['\"]""", re.I), "high"),
    ("db_connection_string", re.compile(r"(?:postgres|mysql|mongodb|redis)://[^\s]{10,}", re.I), "high"),
]

_PII_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    ("us_ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "critical"),
    ("credit_card", re.compile(r"\b(?:4\d{3}|5[1-5]\d{2}|3[47]\d{2})[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{1,4}\b"), "critical"),
    ("email", re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"), "medium"),
]

_INJECTION_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    ("prompt_override", re.compile(r"(?i)ignore\s+(all\s+)?(previous|prior|above)\s+(instructions?|prompts?|rules?)"), "high"),
    ("prompt_override", re.compile(r"(?i)disregard\s+(?:all\s+)?(?:previous|prior|your)\s+(?:instructions?|programming|rules?)"), "high"),
    ("identity_override", re.compile(r"(?i)you\s+are\s+now\s+(?:a\s+)?(?:different|new|my)"), "high"),
    ("pairing_coerce", re.compile(r"(?i)(?:approve|confirm)\s+(?:the\s+)?(?:pairing|device|passkey|enrollment)"), "high"),
    ("exfiltration", re.compile(r"(?i)(?:send|post|upload|exfiltrate)\s+(?:.*\s+)?(?:https?://|my\s+server)"), "high"),
    ("jailbreak", re.compile(r"(?i)\bdo\s+anything\s+now\b|\bDAN\b"), "medium"),
]


def _mode(env_key: str, default: Mode) -> Mode:
    raw = (os.environ.get(env_key) or default.value).strip().lower()
    try:
        return Mode(raw)
    except ValueError:
        return default


def secrets_mode() -> Mode:
    return _mode("FRIDAY_SECRETS_MODE", Mode.REDACT)


def injection_mode() -> Mode:
    return _mode("FRIDAY_INJECTION_MODE", Mode.WARN)


def _collect(text: str, patterns: Iterable[tuple[str, re.Pattern[str], str]]) -> list[Finding]:
    out: list[Finding] = []
    for label, rx, sev in patterns:
        for m in rx.finditer(text or ""):
            out.append(Finding(kind=label.split("_")[0] if False else label, label=label, severity=sev, matched=m.group(0)[:80]))
    return out


def scan_secrets(text: str) -> list[Finding]:
    return _collect(text, _SECRET_PATTERNS)


def scan_pii(text: str) -> list[Finding]:
    return _collect(text, _PII_PATTERNS)


def scan_injection(text: str) -> list[Finding]:
    return _collect(text, _INJECTION_PATTERNS)


def redact_secrets(text: str) -> str:
    out = text or ""
    for label, rx, _sev in _SECRET_PATTERNS:
        out = rx.sub(f"[REDACTED:{label}]", out)
    return out


def apply_secrets(text: str, *, mode: Mode | None = None, audit_tool: str = "content_scan") -> ScanReport:
    mode = mode or secrets_mode()
    findings = scan_secrets(text) + scan_pii(text)
    report = ScanReport(findings=list(findings), text=text or "")
    if not findings:
        return report
    _audit_findings(audit_tool, findings, mode)
    if mode == Mode.BLOCK:
        report.blocked = True
        report.text = ""
        return report
    if mode == Mode.REDACT:
        report.text = redact_secrets(text or "")
        # light PII redaction for SSN / cards only
        for label, rx, sev in _PII_PATTERNS:
            if sev == "critical":
                report.text = rx.sub(f"[REDACTED:{label}]", report.text)
        return report
    # WARN: leave text, findings audited
    return report


def scan_speech(text: str) -> ScanReport:
    """Scan before TTS — never speak secrets; redact by default."""
    return apply_secrets(text, mode=secrets_mode(), audit_tool="voice_speak_scan")


def apply_injection(text: str, *, mode: Mode | None = None, audit_tool: str = "injection_scan") -> ScanReport:
    mode = mode or injection_mode()
    findings = scan_injection(text)
    report = ScanReport(findings=findings, text=text or "")
    if not findings:
        return report
    _audit_findings(audit_tool, findings, mode)
    if mode == Mode.BLOCK:
        report.blocked = True
    return report


def _audit_findings(tool: str, findings: list[Finding], mode: Mode) -> None:
    try:
        from friday.safety.audit import get_audit_log

        get_audit_log().record(
            tool=tool,
            args={"count": len(findings), "kinds": [f.label for f in findings[:12]]},
            outcome="blocked" if mode == Mode.BLOCK else ("redacted" if mode == Mode.REDACT else "warn"),
            approver=f"content_scan:{mode.value}",
            risk="confirm",
            detail="; ".join(f"{f.label}:{f.severity}" for f in findings[:8]),
        )
    except Exception:
        pass
