"""Ref and path guard before push. Run with: python scripts/pre_push_guard.py

Blocks pushing refs that must stay private (archive/*, upgrade/*, stage-*)
and any commit that tracks .internal/ or common secret paths.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_REF_PREFIXES = ("archive/", "upgrade/", "stage-")
FORBIDDEN_TRACKED_PREFIXES = (".internal/",)
FORBIDDEN_TRACKED_EXACT = {
    "data/calendar_ical.url",
}


def _git(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def refs_being_pushed() -> list[str]:
    r = _git(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"])
    upstream = r.stdout.strip() if r.returncode == 0 else ""
    if not upstream:
        branch = _git(["rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
        return [f"refs/heads/{branch}"] if branch and branch != "HEAD" else []
    local = upstream.split("/", 1)[-1] if upstream.startswith("refs/heads/") else upstream
    return [f"refs/heads/{local}"]


def forbidden_ref(name: str) -> str | None:
    short = name.replace("refs/heads/", "").replace("refs/tags/", "")
    for prefix in FORBIDDEN_REF_PREFIXES:
        if short == prefix.rstrip("/") or short.startswith(prefix):
            return prefix
    if re.match(r"^stage-", short):
        return "stage-*"
    return None


def tracked_forbidden_paths() -> list[str]:
    r = _git(["ls-files"])
    if r.returncode != 0:
        return []
    bad: list[str] = []
    for line in r.stdout.splitlines():
        rel = line.strip().replace("\\", "/")
        if not rel:
            continue
        if rel in FORBIDDEN_TRACKED_EXACT:
            bad.append(rel)
            continue
        for prefix in FORBIDDEN_TRACKED_PREFIXES:
            if rel.startswith(prefix):
                bad.append(rel)
    return bad


def main() -> int:
    findings: list[str] = []
    for ref in refs_being_pushed():
        why = forbidden_ref(ref)
        if why:
            findings.append(f"ref {ref} matches forbidden pattern {why!r}")

    for path in tracked_forbidden_paths():
        findings.append(f"tracked path must not be public: {path}")

    if findings:
        print("[pre-push-guard] FAIL:", file=sys.stderr)
        for line in findings:
            print(f"  - {line}", file=sys.stderr)
        print(
            "[pre-push-guard] Use branch release/clean for public pushes. "
            "Never push archive/*, upgrade/*, or stage-* refs.",
            file=sys.stderr,
        )
        return 1
    print("[pre-push-guard] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
