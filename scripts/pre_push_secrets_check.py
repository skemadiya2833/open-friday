"""Local pre-push secrets scan. No CI — run this before any push.

Scans tracked + staged files (and optionally the working tree) for:
- .env contents / API keys / bearer tokens
- private keys
- data/tls certificates and keys
- audit / memory / conversation dumps that must not leave the machine

Exit 0 = clean. Exit 1 = findings. Never prints the secret itself, only path + rule.

Usage:
    python scripts/pre_push_secrets_check.py
    python scripts/pre_push_secrets_check.py --staged-only
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Paths that must never be committed (even if force-added).
FORBIDDEN_PATH_PREFIXES = (
    "data/tls/",
    "data/audit/",
    "data/chroma/",
    "data/conversations/",
    "data/logs/",
    "data/memory/",
    "data/tasks.sqlite",
)
FORBIDDEN_BASENAMES = {
    ".env",
    ".env.local",
    ".env.production",
    "lan.crt",
    "lan.key",
    "id_rsa",
    "id_ed25519",
    "private_key.pem",
}

# Content patterns — matched against file text. Keep groups non-capturing where possible.
CONTENT_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("private_key_pem", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github_pat", re.compile(r"\bghp_[A-Za-z0-9]{20,}\b")),
    ("github_oauth", re.compile(r"\bgho_[A-Za-z0-9]{20,}\b")),
    # Real OpenAI keys are sk-proj-… or long sk-…; ignore short test stubs like sk-abcdefghijklmnopqrstuvwxyz0123456789 used in redaction tests.
    ("openai_sk", re.compile(r"\bsk-(?:proj-|live-|test-)[A-Za-z0-9_\-]{16,}\b")),
    ("gemini_key_assign", re.compile(r"(?i)\bGEMINI_API_KEY\s*=\s*['\"]?(?!your_|changeme|xxx|placeholder)[A-Za-z0-9_\-]{16,}")),
    ("openai_key_assign", re.compile(r"(?i)\bOPENAI_API_KEY\s*=\s*['\"]?(?!your_|changeme|xxx|placeholder)[A-Za-z0-9_\-]{16,}")),
    ("friday_token_assign", re.compile(r"(?i)\bFRIDAY_API_TOKEN\s*=\s*['\"]?(?!your_|changeme|xxx|placeholder|$)[A-Za-z0-9_\-]{8,}")),
    ("generic_api_key_assign", re.compile(r"(?i)\b(?:API_KEY|SECRET_KEY|ACCESS_TOKEN)\s*=\s*['\"](?!your_|changeme|xxx|placeholder)[^'\"\s]{12,}['\"]")),
    ("bearer_literal", re.compile(r"(?i)authorization:\s*bearer\s+[A-Za-z0-9\-_.]{20,}")),
]

SKIP_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".woff", ".woff2",
    ".ttf", ".otf", ".mp3", ".wav", ".mp4", ".zip", ".gz", ".7z", ".exe",
    ".dll", ".pyd", ".so", ".bin", ".sqlite", ".db",
}
SKIP_DIR_PARTS = {".git", "friday_env", "node_modules", "__pycache__", ".venv", "venv", "web/dist"}

# Allowlisted example files (placeholders only).
ALLOWLIST_PATHS = {
    ".env.example",
    "docs/VOICE_SAMPLES.md",
}


def _git(args: list[str]) -> str:
    r = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if r.returncode != 0:
        return ""
    return r.stdout


def list_files(*, staged_only: bool) -> list[Path]:
    out: set[str] = set()
    if staged_only:
        staged = _git(["diff", "--cached", "--name-only", "--diff-filter=ACMR"])
        out.update(p.strip().replace("\\", "/") for p in staged.splitlines() if p.strip())
    else:
        tracked = _git(["ls-files"])
        out.update(p.strip().replace("\\", "/") for p in tracked.splitlines() if p.strip())
        staged = _git(["diff", "--cached", "--name-only", "--diff-filter=ACMR"])
        out.update(p.strip().replace("\\", "/") for p in staged.splitlines() if p.strip())
    paths: list[Path] = []
    for rel in sorted(out):
        if any(part in SKIP_DIR_PARTS for part in rel.replace("\\", "/").split("/")):
            continue
        p = ROOT / rel
        if not p.is_file():
            continue
        if p.suffix.lower() in SKIP_SUFFIXES:
            continue
        paths.append(p)
    return paths


def _norm_rel(rel: str) -> str:
    norm = rel.replace("\\", "/")
    while norm.startswith("./"):
        norm = norm[2:]
    return norm


def path_forbidden(rel: str) -> str | None:
    norm = _norm_rel(rel)
    base = Path(norm).name
    if base in FORBIDDEN_BASENAMES or norm in FORBIDDEN_BASENAMES:
        return f"forbidden_basename:{base}"
    for prefix in FORBIDDEN_PATH_PREFIXES:
        if norm == prefix.rstrip("/") or norm.startswith(prefix):
            return f"forbidden_path:{prefix}"
    if norm.endswith(".pem") and "private" in norm.lower():
        return "forbidden_pem"
    if norm.endswith((".crt", ".key")) and ("tls" in norm or "data/" in norm):
        return "forbidden_tls"
    return None


def scan_content(rel: str, text: str) -> list[str]:
    if rel.replace("\\", "/") in ALLOWLIST_PATHS:
        return []
    hits: list[str] = []
    for name, pat in CONTENT_RULES:
        if pat.search(text):
            hits.append(name)
    return hits


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Local secrets scan before push")
    ap.add_argument("--staged-only", action="store_true", help="Only scan the index")
    args = ap.parse_args(argv)

    findings: list[str] = []
    for path in list_files(staged_only=args.staged_only):
        rel = path.relative_to(ROOT).as_posix()
        why = path_forbidden(rel)
        if why:
            findings.append(f"{rel}: {why}")
            continue
        try:
            raw = path.read_bytes()
        except OSError as exc:
            findings.append(f"{rel}: unreadable ({exc})")
            continue
        if b"\0" in raw[:4096]:
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("utf-8", errors="replace")
        for rule in scan_content(rel, text):
            findings.append(f"{rel}: {rule}")

    if findings:
        print("[secrets-check] FAIL — possible secrets or private data:", file=sys.stderr)
        for line in findings:
            print(f"  - {line}", file=sys.stderr)
        print(
            "[secrets-check] Remove the file from the commit / rotate the secret. "
            "Do not push.",
            file=sys.stderr,
        )
        return 1
    print("[secrets-check] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
