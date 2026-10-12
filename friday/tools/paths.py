"""Workspace path containment.

The previous check compared strings (`str(target).startswith(str(root))`), which
lets a sibling directory such as ``workspace_evil`` pass. This module uses real
path semantics: resolve both sides (following symlinks and junctions) and require
``target`` to be ``root`` or a descendant of it.
"""

from __future__ import annotations

import ntpath
import os
import re
from pathlib import Path

# Windows device names that must never be opened through a user-supplied path.
_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
_DRIVE_RE = re.compile(r"^[A-Za-z]:")


class PathEscapeError(ValueError):
    """Raised when a requested path leaves the sandbox root."""


def _reject_suspicious(rel: str) -> None:
    if "\x00" in rel:
        raise PathEscapeError("NUL byte in path")
    if rel.startswith(("\\\\", "//")):
        raise PathEscapeError("UNC / device paths are not allowed")
    if _DRIVE_RE.match(rel):
        # Covers both absolute ("C:\\x") and drive-relative ("C:x") forms.
        raise PathEscapeError("Drive-qualified paths are not allowed")
    # Alternate data streams: "name.txt:stream" (a colon anywhere after a drive spec).
    if ":" in rel:
        raise PathEscapeError("':' is not allowed in sandbox paths")
    for part in re.split(r"[\\/]+", rel):
        stem = part.split(".")[0].rstrip(" ").upper()
        if stem in _RESERVED:
            raise PathEscapeError(f"Reserved device name: {part}")


def resolve_within(root: str | os.PathLike[str], rel: str | os.PathLike[str] = ".") -> Path:
    """Resolve ``rel`` under ``root`` or raise :class:`PathEscapeError`.

    * ``..`` traversal, absolute paths, drive letters, UNC paths, device names and
      alternate data streams are rejected.
    * Symlinks and directory junctions are followed by ``Path.resolve`` and the
      *final* location must still be inside ``root``.
    * Works for paths that do not exist yet (``strict=False``), so it can guard writes.
    """
    rel_s = os.fspath(rel) or "."
    _reject_suspicious(rel_s)
    if ntpath.isabs(rel_s) or os.path.isabs(rel_s) or rel_s.startswith(("/", "\\")):
        raise PathEscapeError("Absolute paths are not allowed")

    root_resolved = Path(root).resolve()
    candidate = (root_resolved / rel_s).resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise PathEscapeError("Path escapes workspace sandbox") from exc

    # Defend against a symlink/junction *inside* the tree that points outside,
    # even when only an intermediate component is a link (resolve handles it, but
    # re-check each existing ancestor to give a precise error and to stay safe if
    # resolve() semantics change).
    cur = candidate
    while cur != root_resolved and cur != cur.parent:
        if cur.exists():
            real = Path(os.path.realpath(cur))
            try:
                real.relative_to(root_resolved)
            except ValueError as exc:
                raise PathEscapeError("Path resolves outside workspace (link)") from exc
        cur = cur.parent
    return candidate
