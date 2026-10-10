"""F3: does the emergency-stop hotkey collide with other software on this PC?

1. RegisterHotKey probe: a combination that is already registered globally by another program fails with
   ERROR_HOTKEY_ALREADY_REGISTERED (1409). Run this while Friday is NOT running.
2. Config scan: well-known per-app hotkey stores (OBS, VS Code/Cursor keybindings, NVIDIA/AMD/Intel overlays can not
   be read reliably, so they are listed as "unknown", not "free").

    python scripts/hotkey_collision_check.py --out docs/research/hotkey_collision.json
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import sys
from pathlib import Path

MOD = {"alt": 1, "ctrl": 2, "shift": 4, "win": 8}
VK = {f"f{i}": 0x6F + i for i in range(1, 25)}
VK.update({"pause": 0x13, "scrolllock": 0x91, "home": 0x24, "end": 0x23, "delete": 0x2E, "insert": 0x2D})
CANDIDATES = ["ctrl+alt+f12", "ctrl+alt+shift+f12", "ctrl+shift+f12", "ctrl+alt+pause", "ctrl+alt+shift+pause",
              "ctrl+alt+shift+f11", "ctrl+alt+shift+f10", "ctrl+win+shift+f12", "ctrl+alt+shift+delete"]


def probe(spec: str) -> str:
    parts = spec.lower().split("+")
    mods = sum(MOD[p] for p in parts[:-1])
    vk = VK[parts[-1]]
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    ok = user32.RegisterHotKey(None, 0x7A11, mods | 0x4000, vk)       # MOD_NOREPEAT
    if ok:
        user32.UnregisterHotKey(None, 0x7A11)
        return "free"
    err = kernel32.GetLastError()
    return "TAKEN (1409)" if err == 1409 else f"error {err}"


def scan_configs(spec: str) -> list[str]:
    hits = []
    key = spec.lower()
    parts = key.split("+")
    last = parts[-1]
    roots = [Path(os.environ.get("APPDATA", "")) / "obs-studio", Path(os.environ.get("APPDATA", "")) / "Cursor" / "User",
             Path(os.environ.get("APPDATA", "")) / "Code" / "User"]
    for root in roots:
        if not root.exists():
            continue
        for p in list(root.rglob("*.json"))[:400]:
            try:
                txt = p.read_text(encoding="utf-8", errors="ignore").lower()
            except OSError:
                continue
            if p.name == "keybindings.json" and re.search(rf"ctrl\+alt\+{last}\b", txt):
                hits.append(f"{p}: keybinding mentions ctrl+alt+{last}")
            if "obs-studio" in str(p) and '"hotkeys"' in txt and f'"key": "obs_key_{last}"' in txt.replace("'", '"'):
                hits.append(f"{p}: OBS hotkey bound to {last}")
    return hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    res = {"probe": {c: probe(c) for c in CANDIDATES}, "config_hits": {c: scan_configs(c) for c in CANDIDATES[:2]},
           "not_checkable": ["NVIDIA App / GeForce overlay", "AMD Software overlay", "SignalRGB", "Steam overlay", "game launchers"],
           "known_history": "Ctrl+Alt+F12 is the classic Intel graphics 'options' hotkey on some Intel driver versions; "
                            "this PC has no Intel GPU (AMD iGPU + NVIDIA)."}
    print(json.dumps(res, indent=1))
    if a.out:
        Path(a.out).write_text(json.dumps(res, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
