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
from typing import Callable


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
_OPEN_GCAL = re.compile(
    r"^\s*(?:please\s+|hey\s+friday[,:]?\s*)?(?:open|launch|show|bring up|pull up)\s+"
    r"(?:(?:my|the)\s+)?(?:google\s+)?calendar(?:\s+(?P<view>day|week|agenda|today))?\s*"
    r"(?:(?:in|with)\s+(?:chrome|the\s+browser))?\s*[.!]?\s*$",
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
# "Resources on the system", "system specs", "my specification" — never vision-type into the HUD.
_SPECS_TOPIC = (
    r"(?:system\s+specs?|system\s+info(?:rmation)?|hardware\s+(?:info|specs?|resources?)|"
    r"pc\s+specs?|computer\s+specs?|device\s+specs?|"
    r"my\s+specs?|my\s+specifications?|(?:the\s+)?specifications?|"
    r"(?:my\s+)?system\s+resources?|resources?.{0,40}on\s+(?:the\s+)?system|"
    r"machine\s+(?:specs?|info|specifications?))"
)
_SHOW_SPECS_ON_SCREEN = re.compile(
    rf"\b(?:show|display|put|bring up|pull up|open|list)\b.{{0,120}}{_SPECS_TOPIC}\b|"
    rf"\b{_SPECS_TOPIC}\b.{{0,80}}\b(?:on (?:my |the )?(?:screen|desktop|monitor|display)|"
    r"in (?:a |my )?notepad|in (?:a |the )?browser|as html|html)\b|"
    # Voice: "list of my specification and put it on my screen"
    r"\b(?:list|show|put|display)\b.{0,80}\bspecifications?\b.{0,60}\b"
    r"(?:on (?:my |the )?(?:screen|desktop|monitor|display)|put (?:it |them )?on)\b|"
    rf"^\s*(?:please\s+)?{_SPECS_TOPIC}\s*\??\s*$",
    re.I,
)
# Terminal-shaped work — prefer PowerShell over vision/mouse.
_SHELL_FIRST = re.compile(
    r"\b("
    r"git\b|npm\b|npx\b|pnpm\b|yarn\b|pip\b|uv\b|cargo\b|dotnet\b|go\b|"
    r"winget\b|choco\b|scoop\b|"
    r"run (this )?(in )?(powershell|pwsh|cmd|the terminal|terminal)|"
    r"(in|via|using|with)\s+(powershell|pwsh|cmd|the terminal|a terminal)|"
    r"powershell\b|pwsh\b|"
    r"(list|show|check|get|what)\b.{0,50}\b(files?|dirs?|directories|folder|processes?|ports?|"
    r"services?|disk|drives?|path|env|environment|ip|hostname|uptime)|"
    r"processes?\b.{0,40}\b(using|cpu|ram|memory|running)|"
    r"(disk|free)\s+space|whoami|hostname|"
    r"(create|make)\b.{0,30}\b(folder|directory)|"
    r"(delete|remove)\b.{0,30}\b(file|folder|directory)|"
    r"kill (?:process|pid)|stop[- ]process|restart[- ]service|"
    r"clone\b.{0,40}\b(repo|git)|"
    r"install\b.{0,40}\b(package|dependency|dependencies|winget|npm|pip)|"
    r"what(?:'s| is) (?:my )?(?:ip|hostname|uptime)|"
    r"ls\b|dir\b|pwd\b"
    r")",
    re.I,
)
_GUI_REQUIRED = re.compile(
    r"\b("
    r"click|double[- ]?click|drag|draw|paint|mouse|"
    r"fill (?:out |in )?(?:the )?(?:form|dialog|field)|"
    r"in (?:chrome|edge|firefox|word|excel|photoshop|figma|discord|slack|notepad)\b|"
    r"on (?:the |my )?screen (?:and )?(?:click|type|select|drag)|"
    r"browser (?:ui|button)|"
    r"visual(?:ly)?\b|"
    r"see (?:if|whether) .{0,50}\b(?:button|dialog|window|pixel)"
    r")",
    re.I,
)

# Inventory: cameras, USB, displays, audio, printers — measured via PowerShell / OpenCV.
_PERIPHERALS = re.compile(
    r"\b(?:list|show|what|which|enumerate|inventory)\b.{"
    r"0,80}\b(?:peripherals?|devices?|hardware|usb|webcams?|cameras?|web\s*cams?|"
    r"displays?|monitors?|audio|microphones?|speakers?|printers?|"
    r"connected (?:devices?|hardware)|what(?:'s| is) (?:plugged|connected))\b|"
    r"\b(?:how many|list(?: of)?(?: my)?)\b.{0,40}\b(?:cameras?|webcams?|monitors?|displays?)\b|"
    r"^\s*(?:please\s+)?(?:device|peripheral|hardware)\s+(?:list|inventory)\s*\??\s*$",
    re.I,
)
_LIST_CAMERAS = re.compile(
    r"\b(?:list|show|scan|what|which|how many)\b.{0,40}\b(?:cameras?|webcams?|web\s*cams?)\b|"
    r"\bcameras?\s+(?:list|available|connected)\b",
    re.I,
)
# Week / task dashboard as HTML in the browser — never the vision desktop agent.
_WEEK_DASHBOARD = re.compile(
    r"\b("
    r"(?:create|make|build|show|display|open|generate)\b.{0,80}\b"
    r"(?:dashboard|board|overview|visual)\b.{0,80}\b"
    r"(?:week|weekly|tasks?|agenda|plan|calendar)|"
    r"(?:week|weekly)\b.{0,60}\b(?:dashboard|overview|board|visual)|"
    r"dashboard\b.{0,60}\b(?:week|weekly|tasks?|agenda)|"
    r"tasks?\b.{0,40}\b(?:for the week|this week|week)\b.{0,40}\b(?:visual|html|dashboard|screen|display)"
    r")\b",
    re.I,
)
# Write / generate an HTML page → file + browser. Never the vision desktop agent.
_MAKE_HTML = re.compile(
    r"\b("
    r"(?:write|create|make|build|generate|code|draft|spin\s*up)\b.{0,100}\bhtml(?:5)?\b|"
    r"\bhtml(?:5)?\b.{0,80}\b(?:page|file|document|site|webpage|landing|demo|template)\b|"
    r"(?:write|create|make|build|generate)\b.{0,60}\b(?:web\s*page|webpage|landing\s*page)\b"
    r")\b",
    re.I,
)
_MAKE_HTML_VAGUE = re.compile(
    r"^\s*(?:please\s+|hey\s+friday[,:]?\s*)?(?:write|create|make|build|generate|code)\s+"
    r"(?:(?:me\s+|an?\s+|some\s+|the\s+)?)?(?:html(?:5)?(?:\s+code)?(?:\s+file)?|"
    r"an?\s+html(?:5)?\s+page)\s*[.!]?\s*$",
    re.I,
)
_SHOW_TEXT_ON_SCREEN = re.compile(
    r"^\s*(?:please\s+)?(?:show|display|put|write)\b.{"
    r"0,40}\b(?:on (?:my |the )?(?:screen|desktop)|in (?:a |my )?notepad)\b",
    re.I,
)
# Vague "put something on my screen" — ask one question; never start the vision agent.
_SHOW_SOMETHING_VAGUE = re.compile(
    r"\b(?:put|show|display|bring up|pull up)\b.{0,60}\b(?:something|anything|stuff)\b.{0,50}"
    r"\b(?:on (?:my |the )?(?:screen|desktop|monitor)|in (?:the )?browser)\b|"
    r"\b(?:on (?:my |the )?(?:screen|desktop))\b.{0,40}\b(?:something|anything|to show)\b|"
    r"\b(?:put|show)\b.{0,30}\b(?:on (?:my |the )?screen)\b\s*$",
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


def _collect_peripherals() -> str:
    """Cameras (OpenCV + PnP), displays, audio, USB, printers — measured, not invented."""
    lines: list[str] = ["Friday — Peripherals / devices", "=============================="]

    # Cameras via OpenCV probe (same path Systems UI uses).
    try:
        from friday.camera.devices import devices_payload

        payload = devices_payload()
        cams = payload.get("devices") or []
        sel = payload.get("selected_index")
        sel_be = payload.get("selected_backend") or ""
        lines.append(f"Cameras (OpenCV): {len(cams)}")
        if not cams:
            lines.append("  (none opened — close Zoom/Teams/OBS if they lock the device)")
        for d in cams:
            mark = ""
            if d.get("index") == sel and (not sel_be or d.get("backend") == sel_be):
                mark = " ← selected"
            lines.append(
                f"  [{d.get('backend')}:{d.get('index')}] {d.get('name')} "
                f"{d.get('width')}×{d.get('height')}{mark}"
            )
        pnp = payload.get("pnp_names") or []
        if pnp:
            lines.append(f"Windows PnP camera/image names: {len(pnp)}")
            for n in pnp[:12]:
                lines.append(f"  · {n}")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"Cameras: unavailable ({exc})")

    ps = r"""
$ErrorActionPreference = 'SilentlyContinue'
$out = @()
$mons = @(Get-CimInstance Win32_DesktopMonitor | Where-Object { $_.Name })
$out += "Displays: $($mons.Count)"
foreach ($m in $mons) { $out += "  · $($m.Name)" }
try {
  Add-Type -AssemblyName System.Windows.Forms -ErrorAction SilentlyContinue
  $screens = [System.Windows.Forms.Screen]::AllScreens
  $out += "Active screens: $($screens.Count)"
  foreach ($s in $screens) {
    $out += "  · $($s.DeviceName) $($s.Bounds.Width)x$($s.Bounds.Height)$(if($s.Primary){' (primary)'}else{''})"
  }
} catch {}
$audio = @(Get-CimInstance Win32_SoundDevice | Where-Object { $_.Name })
$out += "Audio devices: $($audio.Count)"
foreach ($a in $audio | Select-Object -First 10) { $out += "  · $($a.Name)" }
$usb = @(Get-CimInstance Win32_USBControllerDevice | ForEach-Object {
  [wmi]($_.Dependent)
} | Where-Object { $_.Name } | Select-Object -ExpandProperty Name -Unique)
$out += "USB devices (sample): $([Math]::Min(16,$usb.Count)) of $($usb.Count)"
foreach ($u in $usb | Select-Object -First 16) { $out += "  · $u" }
$printers = @(Get-CimInstance Win32_Printer | Where-Object { $_.Name })
$out += "Printers: $($printers.Count)"
foreach ($p in $printers | Select-Object -First 8) {
  $out += "  · $($p.Name)$(if($p.Default){' (default)'}else{''})"
}
$nics = @(Get-CimInstance Win32_NetworkAdapter | Where-Object { $_.NetEnabled -eq $true -and $_.Name })
$out += "Active network adapters: $($nics.Count)"
foreach ($n in $nics | Select-Object -First 8) { $out += "  · $($n.Name)" }
$out -join "`n"
"""
    out = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
        capture_output=True,
        text=True,
        timeout=30,
    )
    extra = (out.stdout or "").strip()
    if extra:
        lines.append("")
        lines.append(extra)
    lines.append("")
    lines.append(f"Collected : {time.strftime('%Y-%m-%dT%H:%M:%S')}")
    return "\n".join(lines)


def _collect_system_specs() -> str:
    """Real hardware/OS lines via PowerShell (not LLM invention)."""
    ps = r"""
$ErrorActionPreference = 'SilentlyContinue'
$cs = Get-CimInstance Win32_ComputerSystem
$os = Get-CimInstance Win32_OperatingSystem
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
$gpus = @(Get-CimInstance Win32_VideoController | Where-Object { $_.Name })
$disks = @(Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" | ForEach-Object {
  $free = [math]::Round($_.FreeSpace/1GB,1); $tot = [math]::Round($_.Size/1GB,1)
  "$($_.DeviceID) ${free} GB free / ${tot} GB"
})
$ramGB = [math]::Round($cs.TotalPhysicalMemory / 1GB, 1)
$gpuLines = ($gpus | ForEach-Object { $_.Name }) -join '; '
$diskLines = $disks -join '; '
@"
Friday — System specs
=====================
Computer : $($cs.Name)
Manufacturer : $($cs.Manufacturer)
Model : $($cs.Model)
CPU : $($cpu.Name)
Cores / threads : $($cpu.NumberOfCores) / $($cpu.NumberOfLogicalProcessors)
RAM : ${ramGB} GB
GPU : $gpuLines
Disks : $diskLines
OS : $($os.Caption) ($($os.Version)) build $($os.BuildNumber)
User : $env:USERNAME
Collected : $(Get-Date -Format o)
"@
"""
    out = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
        capture_output=True,
        text=True,
        timeout=25,
    )
    text = (out.stdout or "").strip()
    if text:
        # Merge Friday hardware inventory when available (GPU VRAM etc.).
        try:
            from friday.diagnostics.hardware import inventory_summary_for_panel

            inv = inventory_summary_for_panel() or {}
            extra = []
            if inv.get("gpu"):
                extra.append(f"Friday GPU panel : {inv.get('gpu')}")
            if inv.get("vram"):
                extra.append(f"VRAM : {inv.get('vram')}")
            if inv.get("npu"):
                extra.append(f"NPU : {inv.get('npu')}")
            if extra:
                text = text.rstrip() + "\n" + "\n".join(extra)
        except Exception:  # noqa: BLE001
            pass
        return text
    status = _system_status()
    return f"Friday — System specs\n=====================\n{status}\nUser : {os.environ.get('USERNAME', '?')}"


def _specs_to_rows(text: str) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for line in text.splitlines():
        if ":" not in line or line.startswith("=") or line.startswith("Friday"):
            continue
        k, _, v = line.partition(":")
        k, v = k.strip(), v.strip()
        if k and v:
            rows.append((k, v))
    return rows


def _html_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _write_and_open_html(html: str, *, stem: str) -> Path:
    path = Path(tempfile.gettempdir()) / f"{stem}-{int(time.time())}.html"
    path.write_text(html, encoding="utf-8")
    webbrowser.open(path.as_uri())
    return path


_STARTER_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Friday · new page</title>
  <style>
    :root { color-scheme: dark; --bg:#0b1020; --fg:#e8eefc; --accent:#5b8cff; --muted:#8b9bb8; }
    * { box-sizing: border-box; }
    body {
      margin: 0; min-height: 100vh; font-family: "Segoe UI", system-ui, sans-serif;
      background: radial-gradient(1200px 600px at 20% -10%, #1a2a55 0%, var(--bg) 55%);
      color: var(--fg); display: grid; place-items: center; padding: 2rem;
    }
    main {
      width: min(640px, 100%); padding: 2rem 2.25rem; border: 1px solid #243056;
      border-radius: 18px; background: rgba(12, 18, 36, 0.85); backdrop-filter: blur(8px);
    }
    h1 { margin: 0 0 0.4rem; font-size: 1.75rem; letter-spacing: 0.02em; }
    p { margin: 0; color: var(--muted); line-height: 1.55; }
    .tag {
      display: inline-block; margin-bottom: 1rem; padding: 0.2rem 0.55rem;
      border-radius: 999px; font-size: 0.75rem; color: var(--accent);
      border: 1px solid rgba(91, 140, 255, 0.35);
    }
  </style>
</head>
<body>
  <main>
    <span class="tag">FRIDAY · LOCAL</span>
    <h1>Ready when you are</h1>
    <p>Tell Friday what this page should become — a landing page, form, dashboard, whatever —
       and she'll rewrite the file and reopen it.</p>
  </main>
</body>
</html>
"""


def _strip_html_fences(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:html|HTML)?\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
    return t.strip()


def _llm_html_page(brief: str) -> str | None:
    """Generate a single-file HTML page. Fail soft — caller has a starter fallback."""
    brief = (brief or "").strip()[:600]
    if not brief:
        return None
    try:
        from friday.models.local import query_model_text

        prompt = (
            "Write one complete self-contained HTML5 document for this request.\n"
            "Rules: start with <!DOCTYPE html>; inline CSS only; no markdown; no explanation; "
            "polished dark UI; usable as a real page.\n"
            f"Request: {brief}"
        )
        out = query_model_text(prompt, think=False, num_predict=1800, num_ctx=4096)
        raw = ""
        msg = out.get("message")
        if isinstance(msg, str):
            raw = msg.strip()
        elif isinstance(msg, dict):
            raw = str(msg.get("content") or "").strip()
        if not raw:
            raw = str(out.get("raw") or out.get("response") or out.get("text") or "").strip()
        if not raw:
            for v in out.values():
                if isinstance(v, str) and "<html" in v.lower():
                    raw = v
                    break
        html = _strip_html_fences(raw)
        if "<html" in html.lower() and len(html) > 80:
            if not html.lstrip().lower().startswith("<!doctype"):
                html = "<!DOCTYPE html>\n" + html
            return html
    except Exception as exc:  # noqa: BLE001
        print(f"[DirectTools] HTML LLM failed: {exc}")
    return None


def _make_and_open_html(objective: str) -> tuple[Path, str]:
    """Write HTML and open the default browser. Returns (path, how)."""
    obj = (objective or "").strip()
    if _MAKE_HTML_VAGUE.match(obj) or len(obj.split()) <= 5:
        path = _write_and_open_html(_STARTER_HTML, stem="friday-page")
        return path, "starter"
    html = _llm_html_page(obj)
    if html:
        path = _write_and_open_html(html, stem="friday-page")
        return path, "generated"
    path = _write_and_open_html(_STARTER_HTML, stem="friday-page")
    return path, "starter"


def _open_specs_html(text: str, *, stem: str = "friday-system-specs") -> Path:
    """Write a self-contained HTML report and open it in the default browser."""
    rows = _specs_to_rows(text)
    body_rows = "\n".join(
        f"<tr><th>{_html_escape(k)}</th><td>{_html_escape(v)}</td></tr>" for k, v in rows
    ) or f"<tr><td colspan='2'><pre>{_html_escape(text)}</pre></td></tr>"
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Friday — System specs</title>
<style>
  :root {{ color-scheme: dark; --bg:#0b1220; --card:#121a2b; --line:#1e2a44;
           --text:#e8eef9; --muted:#8fa3c4; --accent:#3ecbff; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; font-family: "Segoe UI", system-ui, sans-serif; background:
         radial-gradient(1200px 600px at 10% -10%, #1a2744, var(--bg));
         color: var(--text); min-height: 100vh; padding: 2.5rem 1.25rem; }}
  main {{ max-width: 720px; margin: 0 auto; border: 1px solid var(--line);
         background: var(--card); padding: 1.5rem 1.75rem; }}
  h1 {{ margin: 0 0 .35rem; font-weight: 600; letter-spacing: .04em; font-size: 1.35rem; }}
  .eyebrow {{ color: var(--accent); font-size: .72rem; letter-spacing: .16em; text-transform: uppercase; }}
  p.note {{ color: var(--muted); font-size: .85rem; margin: .75rem 0 1.25rem; }}
  table {{ width: 100%; border-collapse: collapse; }}
  th, td {{ text-align: left; padding: .55rem .4rem; border-bottom: 1px solid var(--line);
            vertical-align: top; font-size: .95rem; }}
  th {{ width: 38%; color: var(--muted); font-weight: 500; }}
  footer {{ margin-top: 1.25rem; color: var(--muted); font-size: .75rem; }}
</style>
</head>
<body>
<main>
  <div class="eyebrow">Friday · local inventory</div>
  <h1>System resources</h1>
  <p class="note">Collected with PowerShell / WMI on this PC — not model-generated.</p>
  <table>{body_rows}</table>
  <footer>File: {stem}.html · Safe to close this tab</footer>
</main>
</body>
</html>
"""
    return _write_and_open_html(html, stem=stem)


def _collect_week_dashboard_data() -> dict:
    """Pull plan + calendar + reminders from SQLite — no model inventing."""
    from datetime import date, timedelta

    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    days = [week_start + timedelta(days=i) for i in range(7)]

    plan_items: list[dict] = []
    try:
        from friday.tasks.plan import get_plan

        plan_items = list(get_plan().get("items") or [])
    except Exception:  # noqa: BLE001
        pass

    cal_by_day: dict[str, list[dict]] = {d.isoformat(): [] for d in days}
    try:
        from friday.calendar.cache import events_for_day, refresh_from_ical

        refresh_from_ical(force=False)
        for d in days:
            for ev in events_for_day(d):
                start = ev.get("start")
                when = "all day" if ev.get("all_day") else (
                    start.strftime("%H:%M") if hasattr(start, "strftime") else ""
                )
                cal_by_day[d.isoformat()].append({
                    "when": when,
                    "title": (ev.get("summary") or "Event").strip(),
                })
    except Exception:  # noqa: BLE001
        pass

    jobs: list[dict] = []
    try:
        from friday.tasks.scheduler import get_scheduler

        for j in get_scheduler().list_jobs():
            if j.get("status") not in ("scheduled", "paused"):
                continue
            when = j.get("cron") and f"cron {j['cron']}" or ""
            if j.get("run_at") and not j.get("cron"):
                when = time.strftime("%a %d %b %H:%M", time.localtime(float(j["run_at"])))
            jobs.append({"title": j.get("title") or "Reminder", "when": when})
    except Exception:  # noqa: BLE001
        pass

    return {
        "today": today.isoformat(),
        "week_start": week_start.isoformat(),
        "days": [{"iso": d.isoformat(), "label": d.strftime("%a %d %b"), "is_today": d == today} for d in days],
        "plan": plan_items,
        "calendar": cal_by_day,
        "reminders": jobs[:12],
    }


def _open_week_dashboard_html() -> Path:
    data = _collect_week_dashboard_data()
    plan_lis = "".join(
        f"<li class=\"{'done' if it.get('done') else ''}\">"
        f"<span class=\"mark\">{'✓' if it.get('done') else '○'}</span> "
        f"{_html_escape(str(it.get('text') or ''))}</li>"
        for it in data["plan"]
    ) or "<li class=\"empty\">No agenda items yet — say what to lock in.</li>"

    day_cols = []
    for d in data["days"]:
        evs = data["calendar"].get(d["iso"]) or []
        ev_html = "".join(
            f"<div class=\"ev\"><span class=\"t\">{_html_escape(e['when'])}</span> "
            f"{_html_escape(e['title'])}</div>"
            for e in evs
        ) or "<div class=\"empty\">—</div>"
        day_cols.append(
            f"<section class=\"day{' today' if d['is_today'] else ''}\">"
            f"<h3>{_html_escape(d['label'])}</h3>{ev_html}</section>"
        )

    rem_lis = "".join(
        f"<li><strong>{_html_escape(j['title'])}</strong> "
        f"<span class=\"muted\">{_html_escape(j['when'])}</span></li>"
        for j in data["reminders"]
    ) or "<li class=\"empty\">No reminders scheduled.</li>"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Friday — Week dashboard</title>
<style>
  :root {{ color-scheme: dark; --bg:#070b14; --card:#10182a; --line:#1c2942;
           --text:#e8eef9; --muted:#8fa3c4; --accent:#3ecbff; --ok:#5dffa8; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; font-family:"Segoe UI",system-ui,sans-serif; color:var(--text);
         background: radial-gradient(900px 500px at 80% -20%, #1a3058, var(--bg));
         min-height:100vh; padding:1.5rem; }}
  header {{ max-width:1100px; margin:0 auto 1.25rem; }}
  .eyebrow {{ color:var(--accent); font-size:.72rem; letter-spacing:.16em; text-transform:uppercase; }}
  h1 {{ margin:.2rem 0; font-weight:600; font-size:1.6rem; }}
  .sub {{ color:var(--muted); font-size:.9rem; }}
  .grid {{ max-width:1100px; margin:0 auto; display:grid; gap:1rem;
          grid-template-columns: minmax(240px, 1fr) minmax(0, 2.2fr); }}
  @media (max-width:860px) {{ .grid {{ grid-template-columns:1fr; }} }}
  .card {{ background:var(--card); border:1px solid var(--line); padding:1rem 1.1rem; }}
  h2 {{ margin:0 0 .75rem; font-size:.95rem; letter-spacing:.06em; text-transform:uppercase; color:var(--muted); }}
  ul {{ list-style:none; margin:0; padding:0; }}
  li {{ padding:.45rem 0; border-bottom:1px solid var(--line); font-size:.95rem; }}
  li.done {{ color:var(--muted); text-decoration:line-through; }}
  li.empty, .empty {{ color:var(--muted); font-size:.85rem; border:0; }}
  .mark {{ color:var(--ok); margin-right:.35rem; }}
  .week {{ display:grid; grid-template-columns:repeat(7,minmax(0,1fr)); gap:.5rem; }}
  @media (max-width:900px) {{ .week {{ grid-template-columns:repeat(2,1fr); }} }}
  .day {{ background:#0c1424; border:1px solid var(--line); padding:.55rem; min-height:7rem; }}
  .day.today {{ border-color:var(--accent); }}
  .day h3 {{ margin:0 0 .45rem; font-size:.72rem; color:var(--accent); letter-spacing:.04em; }}
  .ev {{ font-size:.78rem; margin:.25rem 0; line-height:1.3; }}
  .ev .t {{ color:var(--muted); display:block; font-size:.68rem; }}
  .muted {{ color:var(--muted); font-size:.8rem; margin-left:.35rem; }}
  footer {{ max-width:1100px; margin:1.25rem auto 0; color:var(--muted); font-size:.75rem; }}
</style>
</head>
<body>
<header>
  <div class="eyebrow">Friday · local data</div>
  <h1>Week dashboard</h1>
  <p class="sub">Week of {_html_escape(data['week_start'])} · agenda, calendar, reminders from this PC</p>
</header>
<div class="grid">
  <aside class="card">
    <h2>Today's agenda</h2>
    <ul>{plan_lis}</ul>
    <h2 style="margin-top:1.25rem">Reminders</h2>
    <ul>{rem_lis}</ul>
  </aside>
  <div class="card">
    <h2>Calendar · this week</h2>
    <div class="week">{"".join(day_cols)}</div>
  </div>
</div>
<footer>Opened as a local HTML file — no desktop clicking. Safe to close the tab.</footer>
</body>
</html>
"""
    return _write_and_open_html(html, stem="friday-week-dashboard")


def _open_powershell_specs_window(text: str) -> None:
    """Open a visible PowerShell window that prints the same measured specs."""
    script = Path(tempfile.gettempdir()) / f"friday-specs-{int(time.time())}.ps1"
    # Write body as a separate UTF-8 text file the script prints (no quoting hazards).
    body = Path(tempfile.gettempdir()) / f"friday-specs-{int(time.time())}.txt"
    body.write_text(text.rstrip() + "\n", encoding="utf-8")
    script.write_text(
        "Write-Host ''\n"
        "Write-Host 'Friday — measured system specs' -ForegroundColor Cyan\n"
        "Write-Host ('=' * 40)\n"
        f"Get-Content -LiteralPath '{body}' -Encoding UTF8 | Write-Host\n"
        "Write-Host ''\n"
        "Write-Host 'Press Enter to close…' -ForegroundColor DarkGray\n"
        "Read-Host | Out-Null\n",
        encoding="utf-8",
    )
    subprocess.Popen(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
        ],
        close_fds=True,
    )


def _open_text_on_screen(text: str, *, stem: str = "friday-note") -> Path:
    path = Path(tempfile.gettempdir()) / f"{stem}-{int(time.time())}.txt"
    path.write_text(text.rstrip() + "\n", encoding="utf-8")
    subprocess.Popen(["notepad.exe", str(path)], close_fds=True)
    return path


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


def is_make_html_request(objective: str) -> bool:
    """True when the ask should be write-HTML + open browser (not the vision agent)."""
    obj = (objective or "").strip()
    return bool(obj and _MAKE_HTML.search(obj) and not _WEEK_DASHBOARD.search(obj))


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
        from friday.calendar.create import open_in_chrome

        open_in_chrome(url)
        return DirectResult(True, True, f"Opened {url}", "open_url")

    m = _OPEN_GCAL.match(obj)
    if m:
        from friday.calendar.create import (
            google_calendar_agenda_url,
            google_calendar_day_url,
            google_calendar_week_url,
            open_in_chrome,
        )

        view = (m.group("view") or "week").lower()
        if view in {"day", "today"}:
            url = google_calendar_day_url()
            label = "day"
        elif view == "agenda":
            url = google_calendar_agenda_url()
            label = "agenda"
        else:
            url = google_calendar_week_url()
            label = "week"
        info = open_in_chrome(url)
        browser = info.get("browser") or "browser"
        return DirectResult(
            True,
            True,
            f"Opened Google Calendar ({label}) in {browser}.",
            "open_calendar",
        )

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

    # Week / task dashboard → HTML in browser (never vision desktop agent).
    if _WEEK_DASHBOARD.search(obj):
        try:
            path = _open_week_dashboard_html()
            return DirectResult(
                True,
                True,
                f"Opened your week dashboard in the browser ({path.name}). "
                "Agenda, calendar, and reminders — no desktop clicking.",
                "week_dashboard",
            )
        except Exception as exc:  # noqa: BLE001
            return DirectResult(True, False, f"Couldn't open week dashboard: {exc}", "week_dashboard")

    # Write / generate HTML → temp file + default browser (never vision desktop agent).
    if _MAKE_HTML.search(obj) and not _WEEK_DASHBOARD.search(obj):
        try:
            path, how = _make_and_open_html(obj)
            if how == "starter":
                msg = (
                    f"Opened a starter HTML page in your browser ({path.name}). "
                    "Tell me what you want on it and I'll rewrite it."
                )
            else:
                msg = f"Wrote the HTML and opened it in your browser ({path.name})."
            return DirectResult(True, True, msg, "make_html")
        except Exception as exc:  # noqa: BLE001
            return DirectResult(True, False, f"Couldn't write/open HTML: {exc}", "make_html")

    # Vague "put something on screen" → one clarifying question (no vision loop, no RESULT spam).
    if _SHOW_SOMETHING_VAGUE.search(obj) and not _SHOW_SPECS_ON_SCREEN.search(obj):
        return DirectResult(
            True,
            True,
            "What should I put on screen — your tasks, system specs, a note, or an HTML page?",
            "clarify_screen",
        )

    # Cameras / peripherals inventory (before generic specs — more specific).
    if _LIST_CAMERAS.search(obj) or _PERIPHERALS.search(obj):
        try:
            text = _collect_peripherals()
            # Always open HTML so live mode users can actually see the list.
            html_path = _open_specs_html(text, stem="friday-peripherals")
            return DirectResult(
                True,
                True,
                f"{text}\n\nOpened as HTML ({html_path.name}).",
                "list_peripherals",
            )
        except Exception as exc:  # noqa: BLE001
            return DirectResult(True, False, f"Couldn't list devices: {exc}", "list_peripherals")

    if _SHOW_SPECS_ON_SCREEN.search(obj):
        try:
            specs = _collect_system_specs()
            html_path = _open_specs_html(specs, stem="friday-system-specs")
            # Visible PowerShell listing (measured data only) + HTML in the browser.
            try:
                _open_powershell_specs_window(specs)
            except Exception:  # noqa: BLE001
                pass
            return DirectResult(
                True,
                True,
                f"Collected real system specs via PowerShell and opened them as HTML "
                f"({html_path.name}) plus a PowerShell window. No desktop clicking.",
                "show_specs_on_screen",
            )
        except Exception as exc:  # noqa: BLE001
            return DirectResult(True, False, f"Couldn't put specs on screen: {exc}", "show_specs_on_screen")

    # Generic "put/show X on screen" → Notepad with the requested text (no LLM).
    if _SHOW_TEXT_ON_SCREEN.search(obj) and not re.search(
        r"\b(screenshot|what(?:'s| is) on|describe)\b", obj, re.I
    ):
        body = re.sub(
            r"^\s*(?:please\s+)?(?:show|display|put|write)\s+",
            "",
            obj,
            count=1,
            flags=re.I,
        )
        body = re.sub(
            r"\s+(?:on (?:my |the )?(?:screen|desktop|monitor|display)|in (?:a |my )?notepad)\s*\.?$",
            "",
            body,
            flags=re.I,
        ).strip(" :\"'")
        if len(body) >= 2:
            try:
                path = _open_text_on_screen(body, stem="friday-on-screen")
                return DirectResult(
                    True,
                    True,
                    f"Opened Notepad with that on screen ({path.name}).",
                    "show_text_on_screen",
                )
            except Exception as exc:  # noqa: BLE001
                return DirectResult(True, False, f"Couldn't open Notepad: {exc}", "show_text_on_screen")

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

    # Terminal-first: PowerShell before the vision desktop agent.
    shell = _try_shell_first(obj)
    if shell.handled:
        return shell

    return DirectResult(False)


def is_shell_first_candidate(text: str) -> bool:
    """True when the ask is terminal-shaped and does not clearly require a GUI."""
    t = (text or "").strip()
    if not t or len(t) > 500:
        return False
    if _GUI_REQUIRED.search(t):
        return False
    return bool(_SHELL_FIRST.search(t))


def _propose_powershell(user_text: str) -> str | None:
    """Ask the local model for one PowerShell command, or None / GUI."""
    try:
        from friday.models.local import query_model_text

        prompt = (
            "You are Friday on Windows. Propose ONE PowerShell command for the owner request.\n"
            "Rules:\n"
            "- Output ONLY the command line — no markdown, no commentary.\n"
            "- Prefer built-in cmdlets (Get-ChildItem, Get-Process, Get-PSDrive, winget, git).\n"
            "- Never Format-Volume, diskpart wipe, or recursive wipe of system roots.\n"
            "- If this needs a GUI (clicking buttons, drawing, filling a visual form), output exactly: GUI\n"
            f"Owner: {user_text[:400]}\n"
            "Command:"
        )
        out = query_model_text(
            prompt,
            format_json=False,
            think=False,
            num_predict=120,
            num_ctx=1024,
        )
        text = (out.get("message") or out.get("raw") or "").strip()
        if not text or "unreachable" in text.lower():
            return None
        # First non-empty line; strip fences.
        line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
        line = re.sub(r"^```(?:powershell|ps1|pwsh)?\s*", "", line, flags=re.I)
        line = re.sub(r"\s*```$", "", line).strip().strip("`")
        if not line or re.match(r"(?i)^gui\b", line):
            return None
        if len(line) > 800:
            return None
        return line
    except Exception:  # noqa: BLE001
        return None


def _try_shell_first(obj: str) -> DirectResult:
    if not is_shell_first_candidate(obj):
        return DirectResult(False)
    cmd = _propose_powershell(obj)
    if not cmd:
        # Detector said shell-shaped but model declined — let vision try, or ask.
        return DirectResult(False)
    try:
        from friday.tools.registry import call_tool_result

        result = call_tool_result("run_shell", {"command": cmd, "timeout_seconds": 60}, caller="direct_tools")
        text = (result.text() or "").strip()
        if result.denied:
            return DirectResult(
                True,
                False,
                "That needs PowerShell. Enable Shell tools in Systems (still per-command approval), "
                "or approve the next prompt.",
                "shell_first",
            )
        if not text:
            text = "(no output)"
        # Cap spoken/chat dump
        brief = text if len(text) <= 1200 else text[:1200] + "\n…[truncated]"
        ok = not result.is_error
        header = f"Ran in PowerShell:\n`{cmd}`\n\n"
        return DirectResult(True, ok, header + brief, "shell_first")
    except Exception as exc:  # noqa: BLE001
        return DirectResult(True, False, f"Shell path failed: {exc}", "shell_first")
