"""Dependency / repo audit helper (stdlib only).

Queries PyPI JSON and the GitHub REST API and writes machine-readable results,
so compatibility claims in docs/decisions/ are backed by data, not memory.

Usage:
    python scripts/audit_deps.py pypi  [--out docs/decisions/pypi_audit.json]
    python scripts/audit_deps.py github [--out docs/decisions/github_audit.json]

A wheel counts as installable on CPython 3.14 / Windows x64 when its tags allow:
  * cp314-cp314-win_amd64   (also cp314t is NOT counted: free-threaded build)
  * cp3XX-abi3-win_amd64    with XX <= 14
  * py3-none-any / py2.py3-none-any / cp3-none-any
  * py3-none-win_amd64
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

PYPI_PACKAGES = [
    # current dependencies
    "mss", "pillow", "httpx", "pyautogui", "pyperclip", "python-dotenv",
    "google-generativeai", "numpy", "fastapi", "uvicorn", "pydantic", "pyyaml",
    "chromadb", "apscheduler", "pystray", "faster-whisper", "pyttsx3", "edge-tts",
    "python-multipart",
    # candidates
    "google-genai", "mcp", "ctranslate2", "onnxruntime", "onnxruntime-gpu",
    "torch", "openwakeword", "kokoro", "kokoro-onnx", "piper-tts", "silero-vad",
    "sounddevice", "pywinauto", "uiautomation", "playwright", "psutil",
    "nvidia-ml-py", "jsonschema", "pytest", "ruff", "uv", "windows-mcp",
    "pycaw", "pywin32", "comtypes", "keyboard", "pynput", "openai", "tomli-w",
    "webrtcvad", "pyaudio", "soundfile", "misaki", "espeakng-loader",
    "bleak", "homeassistant-api", "pytest-asyncio", "mypy", "pip-tools",
    "pydantic-settings", "keyring",
]

GITHUB_REPOS = [
    "CursorTouch/Windows-MCP", "NousResearch/hermes-agent",
    "Storage1n1/local-computer-use-agent", "microsoft/fara",
    "bytedance/UI-TARS", "bytedance/UI-TARS-desktop", "simular-ai/Agent-S",
    "trycua/cua", "microsoft/OmniParser", "Yan-Labs/GTA1",
    "modelcontextprotocol/python-sdk", "dscripka/openWakeWord",
    "hexgrad/kokoro", "OHF-Voice/piper1-gpl", "rhasspy/piper",
    "SYSTRAN/faster-whisper", "OpenNMT/CTranslate2", "microsoft/playwright-python",
    "agentskills/agentskills", "openai/whisper", "snakers4/silero-vad",
    "microsoft/UFO", "browser-use/browser-use", "OpenRGB/OpenRGB",
    "home-assistant/core", "Genymobile/scrcpy", "microsoft/playwright-mcp",
]

UA = {"User-Agent": "open-friday-audit/1.0", "Accept": "application/json"}


def _get(url: str) -> dict | None:
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return {"_error": f"HTTP {exc.code}"}
    except Exception as exc:  # noqa: BLE001
        return {"_error": str(exc)}


_WHEEL_RE = re.compile(
    r"^(?P<name>.+?)-(?P<ver>[^-]+)(-(?P<build>\d[^-]*))?-"
    r"(?P<py>[^-]+)-(?P<abi>[^-]+)-(?P<plat>[^-]+)\.whl$"
)


def wheel_ok_for_cp314_win(filename: str) -> bool:
    m = _WHEEL_RE.match(filename)
    if not m:
        return False
    pys, abis, plats = m["py"].split("."), m["abi"].split("."), m["plat"].split(".")
    plat_ok = any(p in ("any", "win_amd64") for p in plats)
    if not plat_ok:
        return False
    for py in pys:
        for abi in abis:
            if py == "cp314" and abi == "cp314":
                return True
            if abi == "abi3":
                mm = re.fullmatch(r"cp3(\d+)", py)
                if mm and int(mm.group(1)) <= 14:
                    return True
            if abi == "none" and py in ("py3", "py2.py3", "cp3", "py30") or (
                abi == "none" and py.startswith("py3")
            ):
                return True
    return False


def audit_pypi(name: str) -> dict:
    data = _get(f"https://pypi.org/pypi/{name}/json")
    if not data or "_error" in data:
        return {"name": name, "error": (data or {}).get("_error", "unknown")}
    info = data["info"]
    version = info["version"]
    files = data["urls"]
    wheels = [f for f in files if f["packagetype"] == "bdist_wheel"]
    sdist = [f for f in files if f["packagetype"] == "sdist"]
    ok = [f["filename"] for f in wheels if wheel_ok_for_cp314_win(f["filename"])]
    cp314_native = [f for f in ok if "-cp314-" in f]
    uploaded = max((f["upload_time_iso_8601"] for f in files), default=None)
    lic = info.get("license_expression") or info.get("license") or ""
    if not lic or len(lic) > 80:
        cls = [c for c in info.get("classifiers", []) if c.startswith("License ::")]
        lic = "; ".join(c.split("::")[-1].strip() for c in cls) or (lic[:80] + "...")
    return {
        "name": name,
        "version": version,
        "released": uploaded,
        "license": lic,
        "requires_python": info.get("requires_python"),
        "home": (info.get("project_urls") or {}).get("Homepage")
        or (info.get("project_urls") or {}).get("Source")
        or info.get("home_page"),
        "wheel_count": len(wheels),
        "has_sdist": bool(sdist),
        "cp314_win_wheel": bool(ok),
        "cp314_native_wheel": bool(cp314_native),
        "wheel_examples": ok[:3],
        "yanked": bool(info.get("yanked")),
    }


def audit_github(repo: str) -> dict:
    data = _get(f"https://api.github.com/repos/{repo}")
    if not data or "_error" in data:
        return {"repo": repo, "error": (data or {}).get("_error", "unknown")}
    rel = _get(f"https://api.github.com/repos/{repo}/releases/latest") or {}
    return {
        "repo": repo,
        "full_name": data.get("full_name"),
        "license": (data.get("license") or {}).get("spdx_id"),
        "archived": data.get("archived"),
        "stars": data.get("stargazers_count"),
        "pushed_at": data.get("pushed_at"),
        "created_at": data.get("created_at"),
        "default_branch": data.get("default_branch"),
        "latest_release": rel.get("tag_name") if "_error" not in rel else None,
        "latest_release_date": rel.get("published_at") if "_error" not in rel else None,
        "description": (data.get("description") or "")[:140],
        "open_issues": data.get("open_issues_count"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["pypi", "github"])
    ap.add_argument("--out")
    ap.add_argument("--names", nargs="*")
    args = ap.parse_args()

    if args.mode == "pypi":
        names = args.names or PYPI_PACKAGES
        results = [audit_pypi(n) for n in names]
    else:
        names = args.names or GITHUB_REPOS
        results = [audit_github(n) for n in names]

    out = Path(args.out or f"docs/decisions/{args.mode}_audit.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"wrote {out} ({len(results)} entries)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
