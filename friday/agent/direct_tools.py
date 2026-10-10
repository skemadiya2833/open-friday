"""Direct (non-GUI) actions for tools-first routing.

Prefer these before any click planning. Uses native Win32 / stdlib where possible;
Windows-MCP only when already configured (never auto-starts).
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import time
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass
class DirectResult:
    handled: bool
    ok: bool = False
    message: str = ""
    tool: str = ""


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

_OPEN_URL = re.compile(
    r"^\s*(?:please\s+)?(?:open|go to|navigate to|browse)\s+"
    r"(?P<url>https?://[^\s]+|www\.[^\s]+)\s*$",
    re.I,
)
_OPEN_APP = re.compile(
    r"^\s*(?:please\s+)?open\s+(?P<app>notepad|calculator|calc|settings|explorer|paint|cmd|powershell|"
    r"file explorer|windows settings)\b(?P<rest>.*)$",
    re.I,
)
_OPEN_FOLDER = re.compile(
    r"^\s*(?:please\s+)?(?:open|show)\s+(?:the\s+)?(?:folder|directory)\s+"
    r"(?P<path>\"[^\"]+\"|[A-Za-z]:\\[^\s]+|%USERPROFILE%[^\s]*|~[^\s]*)\s*$",
    re.I,
)
_VOLUME = re.compile(
    r"^\s*(?:please\s+)?(?:set\s+)?(?:volume|sound)\s+(?P<op>mute|unmute|up|down| louder|quieter)\s*$|"
    r"^\s*(?:mute|unmute)\s+(?:the\s+)?(?:volume|sound|audio)\s*$|"
    r"^\s*(?:volume|sound)\s+(?P<pct>\d{1,3})\s*%?\s*$",
    re.I,
)
_MEDIA = re.compile(
    r"^\s*(?:please\s+)?(?:media\s+)?(?P<op>play|pause|play.?pause|next|previous|prev)\s*"
    r"(?:(?:track|song|media))?\s*$",
    re.I,
)
_CLIPBOARD_SET = re.compile(
    r"^\s*(?:please\s+)?(?:copy|put|set)\s+(?:this\s+|the\s+)?(?:text\s+)?(?:to\s+|into\s+)?(?:the\s+)?clipboard\s*:?\s*"
    r"(?P<text>.+)$",
    re.I,
)
_CLIPBOARD_GET = re.compile(
    r"^\s*(?:please\s+)?(?:what(?:'s| is)|show|read|get)\s+(?:(?:on|in|from)\s+)?(?:the\s+)?clipboard\s*\??\s*$",
    re.I,
)
_TIMER = re.compile(
    r"^\s*(?:please\s+)?(?:set\s+)?(?:a\s+)?(?:timer|reminder)\s+(?:for\s+)?(?P<n>\d+)\s*"
    r"(?P<unit>seconds?|secs?|minutes?|mins?|hours?|hrs?)\s*"
    r"(?:(?:to|for|saying|about)\s+(?P<title>.+))?\s*$",
    re.I,
)
_NOTE = re.compile(
    r"^\s*(?:please\s+)?(?:take\s+a\s+note|note\s+that|remember\s+note)\s*:?\s*(?P<text>.+)$",
    re.I,
)
_STATUS = re.compile(
    r"^\s*(?:please\s+)?(?:system\s+status|how(?:'s| is) (?:the )?(?:pc|system|machine)|"
    r"cpu(?: and)?(?:/?| )ram|resource(?:s)?(?: usage)?)\s*\??\s*$",
    re.I,
)
_SCREENSHOT = re.compile(
    r"^\s*(?:please\s+)?(?:screenshot(?: and describe)?|describe (?:my |the )?(?:screen|desktop)|"
    r"what(?:'s| is) on (?:my |the )?screen)\s*\??\s*$",
    re.I,
)
_FOCUS = re.compile(
    r"^\s*(?:please\s+)?(?:focus|bring to front|activate|switch to)\s+(?:the\s+)?(?P<title>.+?)\s*"
    r"(?:window)?\s*$",
    re.I,
)

_APP_CMDS = {
    "notepad": ["notepad.exe"],
    "calculator": ["calc.exe"],
    "calc": ["calc.exe"],
    "settings": ["cmd.exe", "/c", "start", "ms-settings:"],
    "windows settings": ["cmd.exe", "/c", "start", "ms-settings:"],
    "explorer": ["explorer.exe"],
    "file explorer": ["explorer.exe"],
    "paint": ["mspaint.exe"],
    "cmd": ["cmd.exe"],
    "powershell": ["powershell.exe"],
}


def _vk_media(op: str) -> int | None:
    # Virtual-Key codes for media / volume
    table = {
        "mute": 0xAD,
        "unmute": 0xAD,
        "up": 0xAF,
        "down": 0xAE,
        "louder": 0xAF,
        "quieter": 0xAE,
        "play": 0xB3,
        "pause": 0xB3,
        "playpause": 0xB3,
        "play-pause": 0xB3,
        "next": 0xB0,
        "previous": 0xB1,
        "prev": 0xB1,
    }
    return table.get(op.lower().replace(" ", ""))


def _keybd(vk: int) -> None:
    import ctypes

    u = ctypes.windll.user32
    u.keybd_event(vk, 0, 0, 0)
    u.keybd_event(vk, 0, 2, 0)


def _clipboard_set(text: str) -> None:
    # Prefer PowerShell (reliable on modern Windows); ctypes OpenClipboard can AV under pytest.
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command", "Set-Clipboard -Value $input"],
        input=text,
        capture_output=True,
        text=True,
        timeout=8,
    )
    if r.returncode != 0:
        raise OSError(r.stderr.strip() or "Set-Clipboard failed")


def _clipboard_get() -> str:
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"],
        capture_output=True,
        text=True,
        timeout=8,
    )
    if r.returncode != 0:
        raise OSError(r.stderr.strip() or "Get-Clipboard failed")
    return r.stdout or ""


def _system_status() -> str:
    try:
        import psutil  # type: ignore

        cpu = psutil.cpu_percent(interval=0.2)
        mem = psutil.virtual_memory()
        return f"CPU {cpu:.0f}% · RAM {mem.percent:.0f}% used ({mem.used // (1024**3)} / {mem.total // (1024**3)} GB)"
    except Exception:
        # Fallback without psutil
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance Win32_OperatingSystem) | "
             "Select-Object @{N='FreeGB';E={[math]::Round($_.FreePhysicalMemory/1MB,1)}}, "
             "@{N='TotalGB';E={[math]::Round($_.TotalVisibleMemorySize/1MB,1)}} | ConvertTo-Json"],
            capture_output=True, text=True, timeout=8,
        )
        return out.stdout.strip() or "status unavailable"


def _screenshot_describe(*, describe: bool = True) -> str:
    from friday.models.local import describe_screen
    from friday.vision.feed import LiveScreenFeed

    feed = LiveScreenFeed(mask_overlay=False)
    vision = feed.capture_oneshot()
    b64 = vision.frame_b64 if vision else None
    if not b64:
        raise RuntimeError("no screenshot")
    if not describe:
        return f"Screenshot captured ({len(b64)} b64 chars)."
    return describe_screen("What is visibly open on the desktop? Be brief.", frame_b64=b64)


def try_direct(objective: str, *, workspace: str | None = None,
               approve: Callable[[str, str], bool] | None = None) -> DirectResult:
    obj = (objective or "").strip()
    if not obj:
        return DirectResult(False)

    m = _OPEN_URL.match(obj)
    if m:
        url = m.group("url")
        if url.lower().startswith("www."):
            url = "https://" + url
        webbrowser.open(url)
        return DirectResult(True, True, f"Opened {url}", "open_url")

    m = _OPEN_FOLDER.match(obj)
    if m:
        path = m.group("path").strip('"')
        path = os.path.expandvars(os.path.expanduser(path))
        if not Path(path).is_dir():
            return DirectResult(True, False, f"Folder not found: {path}", "open_folder")
        subprocess.Popen(["explorer.exe", path], close_fds=True)
        return DirectResult(True, True, f"Opened folder {path}", "open_folder")

    m = _OPEN_APP.match(obj)
    if m:
        app = m.group("app").lower()
        rest = (m.group("rest") or "").strip()
        # If the rest looks like a full GUI task (type/save), leave for other routers.
        if re.search(r"\b(type|write|save|click)\b", rest, re.I):
            return DirectResult(False)
        cmd = _APP_CMDS.get(app)
        if not cmd:
            return DirectResult(False)
        if app in {"settings", "windows settings"}:
            subprocess.Popen(cmd, shell=False, close_fds=True)
        else:
            subprocess.Popen(cmd, close_fds=True)
        return DirectResult(True, True, f"Launched {app}", "open_app")

    m = _VOLUME.match(obj)
    if m:
        op = (m.group("op") or m.group(0) or "").strip().lower()
        if "mute" in op and "unmute" not in op:
            op = "mute"
        elif "unmute" in op:
            op = "unmute"
        vk = _vk_media(op.split()[0] if op else "")
        if vk is None and m.groupdict().get("pct"):
            # Approximate: nudge volume toward target — only a few taps (safe).
            for _ in range(2):
                _keybd(0xAF)
            return DirectResult(True, True, f"Nudged volume up (target {m.group('pct')}% approximate)", "volume")
        if vk is None:
            return DirectResult(False)
        _keybd(vk)
        return DirectResult(True, True, f"Volume/media key: {op}", "volume")

    m = _MEDIA.match(obj)
    if m:
        vk = _vk_media(m.group("op"))
        if vk is None:
            return DirectResult(False)
        _keybd(vk)
        return DirectResult(True, True, f"Media key: {m.group('op')}", "media")

    if _CLIPBOARD_GET.match(obj):
        try:
            text = _clipboard_get()
        except OSError as exc:
            return DirectResult(True, False, f"Clipboard read failed: {exc}", "clipboard")
        return DirectResult(True, True, f"Clipboard: {text[:500] or '(empty)'}", "clipboard")

    m = _CLIPBOARD_SET.match(obj)
    if m:
        text = m.group("text").strip().strip("\"'")
        try:
            _clipboard_set(text[:4000])
        except OSError as exc:
            return DirectResult(True, False, f"Clipboard write failed: {exc}", "clipboard")
        return DirectResult(True, True, f"Copied {len(text)} characters to the clipboard", "clipboard")

    m = _TIMER.match(obj)
    if m:
        n = int(m.group("n"))
        unit = m.group("unit").lower()
        title = (m.group("title") or "timer").strip()[:120]
        if unit.startswith("sec"):
            delay = float(n)
        elif unit.startswith("min"):
            delay = float(n) * 60
        else:
            delay = float(n) * 3600
        if delay > 24 * 3600:
            return DirectResult(True, False, "Timer too long (max 24h)", "timer")
        from friday.tools.registry import call_tool_result

        out = call_tool_result(
            "schedule_task",
            {"title": title, "delay_seconds": delay, "skill_id": "reminder", "prompt": title},
            caller="direct_tools",
        ).text()
        return DirectResult(True, True, out or f"Timer set for {n} {unit}: {title}", "timer")

    m = _NOTE.match(obj)
    if m:
        text = m.group("text").strip()
        root = Path(workspace or os.getenv("FRIDAY_WORKSPACE") or tempfile.gettempdir()) / "notes"
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"note-{int(time.time())}.txt"
        path.write_text(text + "\n", encoding="utf-8")
        return DirectResult(True, True, f"Note saved to {path}", "note")

    if _STATUS.match(obj):
        return DirectResult(True, True, _system_status(), "system_status")

    if _SCREENSHOT.match(obj):
        try:
            msg = _screenshot_describe(describe=True)
            return DirectResult(True, True, msg, "screenshot_describe")
        except Exception as exc:  # noqa: BLE001
            return DirectResult(True, False, f"Screenshot failed: {exc}", "screenshot_describe")

    m = _FOCUS.match(obj)
    if m and len(m.group("title").split()) <= 6:
        title = m.group("title").strip().strip("\"'")
        # Try Windows-MCP Switch-App / focus if available; else PowerShell AppActivate
        try:
            from friday.mcp_client import get_mcp_manager

            mgr = get_mcp_manager()
            if mgr and any(s.get("name") == "windows" and s.get("running") for s in (mgr.status().get("servers") or [])):
                # Best-effort; fall through to AppActivate on failure
                pass
        except Exception:
            pass
        ps = (
            f"$w = Get-Process | Where-Object {{ $_.MainWindowTitle -match "
            f"[regex]::Escape('{title.replace(chr(39), '')}') }} | Select-Object -First 1; "
            f"if ($w) {{ (New-Object -ComObject WScript.Shell).AppActivate($w.Id) | Out-Null; "
            f"'focused ' + $w.MainWindowTitle }} else {{ 'window not found' }}"
        )
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=8)
        msg = (r.stdout or r.stderr or "").strip()
        ok = "focused" in msg.lower()
        return DirectResult(True, ok, msg or "focus attempted", "focus_window")

    return DirectResult(False)
