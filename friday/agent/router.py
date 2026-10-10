"""Tools-first router: do it without the GUI when a deterministic tool can do it exactly.

Clicking through Notepad to save two lines is slow and fragile (the failure mode this fixes: type "alpha", Enter, click the
first line, type "beta" into the wrong place, wipe it, start over). When an objective is simply "write this text into
that file", writing the file is exact and takes milliseconds. The router recognises a small set of such objectives with
strict patterns; anything it does not fully understand falls through to the normal GUI agent, so it can only ever *add*
reliability. Local and deterministic: no model call, no network.

Safety: absolute paths only, under the user's profile or the temp / workspace dirs, text-like extensions only (never
.bat/.cmd/.ps1/.exe/.lnk/.reg/...), no overwrite, no system/startup/.ssh folders. Paths outside temp/workspace need an
owner approval, which fails closed in unattended runs (the agent then simply uses the GUI path).
"""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from friday.agent import macros as M

SAFE_EXT = {".txt", ".md", ".csv", ".json", ".log", ".yaml", ".yml", ".ini", ".xml", ".html", ".css", ".text"}
_FORBIDDEN_PARTS = ("\\appdata\\roaming\\microsoft\\windows\\start menu", "\\.ssh", "\\startup", "\\windows\\", "\\program files")

_PATH = r'(?P<path>"[A-Za-z]:\\[^"]+"|[A-Za-z]:\\[^\s"\'<>|*?]+(?:\\[^\s"\'<>|*?]+)*\.[A-Za-z0-9]{1,5})'
_SAVE = re.compile(rf"\b(?:and\s+|then\s+)*save(?:\s+(?:the\s+file|it|this|that))?\s+(?:as|to|into|at)\s+{_PATH}\.?\s*(?:\(.*\))?\s*\.?\s*$", re.I)
_OPEN_NOTEPAD = re.compile(r"^\s*(?:please\s+)?open\s+notepad\s*[,.:;]?\s*(?:and\s+|then\s+)?", re.I)


@dataclass
class Routed:
    handled: bool
    ok: bool = False
    message: str = ""
    path: str = ""
    content: str = ""


def _roots(workspace: str | None) -> list[Path]:
    r = [Path(tempfile.gettempdir()).resolve(), Path.home().resolve()]
    if workspace:
        r.append(Path(workspace).resolve())
    return r


def path_allowed(path: Path, workspace: str | None = None) -> str | None:
    """None when writing a NEW text file here is acceptable, else the reason it is not."""
    bad = M.path_problem(str(path))
    if bad:
        return bad
    if path.suffix.lower() not in SAFE_EXT:
        return f"extension {path.suffix or '(none)'} is not a plain-text type"
    low = str(path).lower()
    if any(p in low for p in _FORBIDDEN_PARTS):
        return "system, startup or credentials folder"
    try:
        rp = path.parent.resolve()
    except OSError:
        return "folder does not exist"
    if not rp.is_dir():
        return "folder does not exist"
    if not any(rp == r or r in rp.parents for r in _roots(workspace)):
        return "outside the user profile, temp and workspace folders"
    if path.exists():
        return "file already exists (the router never overwrites)"
    return None


def needs_approval(path: Path, workspace: str | None = None) -> bool:
    """Temp and workspace are scratch space; anything else under the profile is the owner's data."""
    rp = path.parent.resolve()
    scratch = [Path(tempfile.gettempdir()).resolve()] + ([Path(workspace).resolve()] if workspace else [])
    return not any(rp == r or r in rp.parents for r in scratch)


def parse_text_objective(objective: str) -> tuple[str, str] | None:
    """-> (path, content) when the whole objective is 'type X [, press Enter, type Y ...] and save as PATH'."""
    obj = (objective or "").strip()
    m = _SAVE.search(obj)
    if not m:
        return None
    path = m.group("path").strip('"')
    body = obj[: m.start()].strip().rstrip(",;. ")
    body = _OPEN_NOTEPAD.sub("", body, count=1).strip()
    if not body:
        return None
    # split into clauses on commas / "then" / "and then" / "and" before a verb
    clauses = [c.strip(" ,.;") for c in re.split(r",|;|\bthen\b|\band\s+(?=(?:type|press)\b)", body, flags=re.I) if c.strip(" ,.;")]
    out = ""
    for c in clauses:
        low = c.lower()
        if re.fullmatch(r"(?:and\s+)?press\s+enter(?:\s+key)?", low):
            out += "\n"
        elif re.fullmatch(r"(?:and\s+)?select\s+all\s+(?:and\s+)?(?:delete|remove|clear)(?:\s+it)?", low) or \
                re.fullmatch(r"(?:and\s+)?(?:delete|clear)\s+(?:it|everything|all)", low):
            out = ""
        else:
            t = re.fullmatch(r"(?:and\s+)?(?:type|write|enter)\s*:?\s*(?:the\s+word\s+|the\s+text\s+|exactly\s*:?\s*)?(.+)", c, flags=re.I)
            if not t:
                return None                    # a clause we do not fully understand: let the GUI agent handle everything
            txt = t.group(1).strip()
            if txt.startswith(("'", '"')) and txt.endswith(("'", '"')) and len(txt) > 1:
                txt = txt[1:-1]
            out += txt
    return (path, out) if out.strip() else None


def route(objective: str, *, workspace: str | None = None,
          approve: Callable[[str, str], bool] | None = None, writer: Callable[[Path, str], None] | None = None) -> Routed:
    """Try the deterministic tools. ``handled=False`` means: use the GUI agent."""
    # Direct native / MCP-backed actions before any click planning.
    try:
        from friday.agent.direct_tools import try_direct

        d = try_direct(objective, workspace=workspace, approve=approve)
        if d.handled:
            return Routed(True, d.ok, d.message, path=d.tool, content="")
    except Exception as exc:  # noqa: BLE001
        # Never block the GUI agent because a direct tool crashed.
        print(f"[Router] direct tool error: {exc}")

    parsed = parse_text_objective(objective)
    if parsed is None:
        return Routed(False)
    path, content = Path(parsed[0]), parsed[1]
    why = path_allowed(path, workspace)
    if why:
        return Routed(False, message=f"router skipped: {why}")
    if needs_approval(path, workspace):
        if approve is None or not approve(str(path), f"{len(content)} characters of text"):
            return Routed(False, message="router skipped: write needs the owner's approval")
    try:
        (writer or (lambda p, c: p.write_text(c, encoding="utf-8", newline="")))(path, content)
        got = path.read_text(encoding="utf-8")
    except OSError as exc:
        return Routed(False, message=f"router write failed: {exc}")
    if got != content:
        return Routed(False, message="router verification failed (content differs)")
    return Routed(True, True, f"Wrote {len(content)} characters to {path}", str(path), content)


def approval_from_service(run_id: str | None) -> Callable[[str, str], bool]:
    def ask(path: str, what: str) -> bool:
        from friday.safety.approval import get_approval_service

        ok, _ = get_approval_service().request(tool="router_write_file", risk="confirm", args={"path": path, "what": what},
                                               reason="Create this new text file for you without using the GUI?",
                                               caller="router", run_id=run_id)
        return ok
    return ask


def enabled_by_env() -> bool:
    return os.getenv("FRIDAY_TOOLS_FIRST", "true").strip().lower() not in ("0", "false", "no", "off")
