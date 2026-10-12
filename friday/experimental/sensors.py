"""Read-only system sensors. Standard library + ctypes only; no new dependencies, no admin rights.

EXPERIMENTAL and OFF by default: the tool is only registered when ``FRIDAY_SENSORS=true``. It can only
read: it runs nvidia-smi with a fixed argument list, calls three Win32 getters, and (if the owner runs
LibreHardwareMonitor with its web server) GETs http://127.0.0.1:8085/data.json. It never writes anything.

Temperatures on Windows need LibreHardwareMonitor (psutil has no sensors_temperatures() on Windows).
"""

from __future__ import annotations

import ctypes
import json
import shutil
import subprocess
import time
import urllib.request
from ctypes import wintypes
from typing import Any

from friday.tools.types import ToolResult, ToolRisk, ToolSpec, object_schema


class _MemStatus(ctypes.Structure):
    _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD), ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


class _Power(ctypes.Structure):
    _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte), ("BatteryLifePercent", ctypes.c_ubyte),
                ("SystemStatusFlag", ctypes.c_ubyte), ("BatteryLifeTime", wintypes.DWORD), ("BatteryFullLifeTime", wintypes.DWORD)]


class _FT(ctypes.Structure):
    _fields_ = [("lo", wintypes.DWORD), ("hi", wintypes.DWORD)]

    def v(self) -> int:
        return (self.hi << 32) | self.lo


def memory() -> dict[str, Any]:
    m = _MemStatus()
    m.dwLength = ctypes.sizeof(m)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return {"percent_used": int(m.dwMemoryLoad), "total_gb": round(m.ullTotalPhys / 2**30, 1),
            "available_gb": round(m.ullAvailPhys / 2**30, 1)}


def cpu_load(sample_s: float = 0.25) -> float:
    def read():
        i, k, u = _FT(), _FT(), _FT()
        ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(i), ctypes.byref(k), ctypes.byref(u))
        return i.v(), k.v() + u.v()
    i0, t0 = read()
    time.sleep(sample_s)
    i1, t1 = read()
    total = t1 - t0
    return round(100.0 * (1 - (i1 - i0) / total), 1) if total else 0.0


def power() -> dict[str, Any]:
    p = _Power()
    ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(p))
    return {"on_ac": p.ACLineStatus == 1, "battery_percent": None if p.BatteryLifePercent == 255 else int(p.BatteryLifePercent)}


def disks() -> dict[str, Any]:
    out = {}
    for letter in "CDEFG":
        try:
            u = shutil.disk_usage(f"{letter}:\\")
            out[f"{letter}:"] = {"free_gb": round(u.free / 2**30, 1), "total_gb": round(u.total / 2**30, 1)}
        except OSError:
            continue
    return out


def gpu() -> dict[str, Any] | None:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        r = subprocess.run([exe, "--query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total,power.draw,fan.speed",
                            "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5, check=True)
        n, t, u, mu, mt, pw, fan = [x.strip() for x in r.stdout.strip().splitlines()[0].split(",")]
        f = lambda s: None if "N/A" in s or "Not" in s else float(s)  # noqa: E731
        return {"name": n, "temp_c": f(t), "util_percent": f(u), "vram_used_mb": f(mu), "vram_total_mb": f(mt),
                "power_w": f(pw), "fan_percent": f(fan)}
    except Exception:  # noqa: BLE001
        return None


def lhm_temperatures(url: str = "http://127.0.0.1:8085/data.json") -> list[dict[str, str]] | None:
    """Only localhost, only if the owner already runs LibreHardwareMonitor's web server."""
    try:
        with urllib.request.urlopen(url, timeout=1.5) as r:  # noqa: S310 - fixed loopback URL
            tree = json.loads(r.read(2_000_000))
    except Exception:  # noqa: BLE001
        return None
    found: list[dict[str, str]] = []

    def walk(n: dict, path: str) -> None:
        text = str(n.get("Text", ""))
        if n.get("Type") == "Temperature" or str(n.get("Value", "")).endswith("°C"):
            found.append({"sensor": f"{path}/{text}".strip("/"), "value": str(n.get("Value", ""))})
        for c in n.get("Children", []) or []:
            walk(c, f"{path}/{text}" if text else path)

    walk(tree, "")
    return found[:40]


def read_all() -> dict[str, Any]:
    return {"cpu_load_percent": cpu_load(), "memory": memory(), "power": power(), "disks": disks(), "gpu": gpu(),
            "temperatures_lhm": lhm_temperatures(),
            "note": "temperatures_lhm is null unless LibreHardwareMonitor's Remote Web Server is running on 127.0.0.1:8085"}


def _tool(_args: dict[str, Any]) -> ToolResult:
    data = read_all()
    return ToolResult(content=[{"type": "text", "text": json.dumps(data, indent=1)}], structured=data)


def sensor_specs() -> list[ToolSpec]:
    return [ToolSpec("system_sensors", "Read-only snapshot of CPU load, memory, disks, GPU and (if available) temperatures.",
                     object_schema(), _tool, ToolRisk.SAFE, source="experimental")]
