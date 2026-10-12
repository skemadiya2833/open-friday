"""Ensure adapted-from headers and THIRD_PARTY_NOTICES.md stay in sync.

Every Python file with an OpenJarvis / adapted-from header must appear in
docs/THIRD_PARTY_NOTICES.md, and every Friday path listed there must exist.

Exit 0 = OK. Exit 1 = mismatch.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOTICES = ROOT / "docs" / "THIRD_PARTY_NOTICES.md"

HEADER_RE = re.compile(
    r"(?im)^(?:#|//)\s*(?:Copyright.*OpenJarvis|Source:\s*open-jarvis|Licensed under the Apache License)"
)
# Table rows like: | `friday/foo.py` | ...
ROW_RE = re.compile(r"\|\s*`([^`]+)`\s*\|")


def files_with_adapted_headers() -> set[str]:
    found: set[str] = set()
    for path in (ROOT / "friday").rglob("*.py"):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        head = "\n".join(text.splitlines()[:16])
        # Require the standard adapted-file header block (not a mere docstring mention).
        if (
            "Copyright 2025 The OpenJarvis Authors" in head
            and "Source:" in head
            and "Apache License" in head
        ):
            found.add(path.relative_to(ROOT).as_posix())
    return found


def notice_paths() -> set[str]:
    if not NOTICES.is_file():
        return set()
    text = NOTICES.read_text(encoding="utf-8")
    paths = set()
    in_table = False
    for line in text.splitlines():
        if line.strip().startswith("| Friday file"):
            in_table = True
            continue
        if in_table:
            if not line.strip().startswith("|"):
                break
            if re.match(r"\|\s*-+", line):
                continue
            m = ROW_RE.search(line)
            if m:
                paths.add(m.group(1).replace("\\", "/"))
    return paths


def main() -> int:
    adapted = files_with_adapted_headers()
    listed = notice_paths()
    missing_in_notices = sorted(adapted - listed)
    missing_files = sorted(p for p in listed if not (ROOT / p).is_file())
    # Allow listed design-only rows that aren't code — still require file exists
    ok = True
    if missing_in_notices:
        ok = False
        print("[third-party] FAIL — adapted headers not listed in THIRD_PARTY_NOTICES.md:", file=sys.stderr)
        for p in missing_in_notices:
            print(f"  - {p}", file=sys.stderr)
    if missing_files:
        ok = False
        print("[third-party] FAIL — NOTICE paths missing on disk:", file=sys.stderr)
        for p in missing_files:
            print(f"  - {p}", file=sys.stderr)
    if ok:
        print(f"[third-party] OK — {len(adapted)} adapted file(s), {len(listed)} notice row(s)")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
