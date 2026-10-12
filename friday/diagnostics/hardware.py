"""Best-effort hardware inventory (Windows-first, no admin, no installs).

Results for staged experiments belong under ``.internal/hw/`` (gitignored).
"""

from __future__ import annotations

import json
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]


def hw_data_dir() -> Path:
    d = _REPO_ROOT / ".internal" / "hw"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _run_ps(script: str, *, timeout: float = 25.0) -> tuple[str, str, int]:
    if sys.platform != "win32":
        return "", "not-windows", 127
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return (r.stdout or "").strip(), (r.stderr or "").strip(), r.returncode
    except subprocess.TimeoutExpired:
        return "", "timeout", 124
    except Exception as exc:  # noqa: BLE001
        return "", f"{type(exc).__name__}: {exc}", 1


def _json_from_ps(script: str, *, timeout: float = 25.0) -> Any:
    out, err, code = _run_ps(script, timeout=timeout)
    if not out:
        return {"_error": err or f"exit {code}"}
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return {"_raw": out, "_stderr": err}


def _nvidia_smi_gpus() -> list[dict[str, Any]]:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return []
    query = (
        "name,driver_version,memory.total,memory.used,memory.free,"
        "utilization.gpu,utilization.memory,temperature.gpu,power.draw,power.limit,"
        "clocks.current.graphics,clocks.current.memory,fan.speed"
    )
    try:
        r = subprocess.run(
            [exe, f"--query-gpu={query}", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
    except Exception as exc:  # noqa: BLE001
        return [{"source": "nvidia-smi", "error": str(exc)}]

    def _f(v: str) -> float | None:
        v = v.strip()
        if not v or "N/A" in v or "Not" in v:
            return None
        try:
            return float(v)
        except ValueError:
            return None

    rows: list[dict[str, Any]] = []
    for line in (r.stdout or "").strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 13:
            continue
        rows.append(
            {
                "name": parts[0],
                "driver_version": parts[1],
                "vram_total_mb": _f(parts[2]),
                "vram_used_mb": _f(parts[3]),
                "vram_free_mb": _f(parts[4]),
                "gpu_util_pct": _f(parts[5]),
                "mem_util_pct": _f(parts[6]),
                "temp_c": _f(parts[7]),
                "power_draw_w": _f(parts[8]),
                "power_limit_w": _f(parts[9]),
                "clock_graphics_mhz": _f(parts[10]),
                "clock_mem_mhz": _f(parts[11]),
                "fan_pct": _f(parts[12]),
                "source": "nvidia-smi",
            }
        )
    return rows


def _wmi_video_controllers() -> list[dict[str, Any]]:
    script = r"""
$rows = Get-CimInstance Win32_VideoController | ForEach-Object {
  [ordered]@{
    name = $_.Name
    adapter_ram_bytes = [int64]$_.AdapterRAM
    driver_version = $_.DriverVersion
    driver_date = $_.DriverDate
    video_processor = $_.VideoProcessor
    pnp_device_id = $_.PNPDeviceID
    status = $_.Status
    current_resolution = if ($_.CurrentHorizontalResolution) {
      "$($_.CurrentHorizontalResolution)x$($_.CurrentVerticalResolution) @ $($_.CurrentRefreshRate)Hz"
    } else { $null }
    video_mode_description = $_.VideoModeDescription
  }
}
if ($rows -is [array]) { $rows | ConvertTo-Json -Compress -Depth 4 }
elseif ($null -eq $rows) { '[]' }
else { @($rows) | ConvertTo-Json -Compress -Depth 4 }
"""
    data = _json_from_ps(script)
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "name" in data:
        return [data]
    return []


def _wmi_cpu() -> dict[str, Any]:
    script = r"""
$p = Get-CimInstance Win32_Processor | Select-Object -First 1
[ordered]@{
  name = $p.Name
  manufacturer = $p.Manufacturer
  cores = [int]$p.NumberOfCores
  logical_processors = [int]$p.NumberOfLogicalProcessors
  max_clock_mhz = [int]$p.MaxClockSpeed
  socket = $p.SocketDesignation
} | ConvertTo-Json -Compress
"""
    data = _json_from_ps(script)
    return data if isinstance(data, dict) else {}


def _wmi_memory() -> dict[str, Any]:
    script = r"""
$cs = Get-CimInstance Win32_ComputerSystem
$os = Get-CimInstance Win32_OperatingSystem
[ordered]@{
  total_physical_gb = [math]::Round($cs.TotalPhysicalMemory / 1GB, 2)
  free_physical_gb = [math]::Round($os.FreePhysicalMemory / 1024 / 1024, 2)
  total_visible_gb = [math]::Round($os.TotalVisibleMemorySize / 1024 / 1024, 2)
} | ConvertTo-Json -Compress
"""
    data = _json_from_ps(script)
    return data if isinstance(data, dict) else {}


def _wmi_disks() -> list[dict[str, Any]]:
    script = r"""
Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" | ForEach-Object {
  [ordered]@{
    device = $_.DeviceID
    label = $_.VolumeName
    filesystem = $_.FileSystem
    size_gb = [math]::Round($_.Size / 1GB, 2)
    free_gb = [math]::Round($_.FreeSpace / 1GB, 2)
  }
} | ConvertTo-Json -Compress
"""
    data = _json_from_ps(script)
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "device" in data:
        return [data]
    return []


def _detect_npu() -> dict[str, Any]:
    """Ryzen AI / XDNA — registry + PnP, best-effort."""
    script = r"""
$pnps = Get-PnpDevice -ErrorAction SilentlyContinue |
  Where-Object {
    $_.Class -eq 'ComputeAccelerator' -or
    $_.FriendlyName -match 'NPU Compute|XDNA|Ryzen AI' -or
    $_.InstanceId -match 'DEV_1502|XDNA'
  } |
  Select-Object FriendlyName, Class, Status, InstanceId
$reg = $null
foreach ($path in @(
  'HKLM:\SYSTEM\CurrentControlSet\Services\amdxdna',
  'HKLM:\SOFTWARE\AMD\RyzenAI'
)) {
  if (Test-Path $path) { $reg = $path; break }
}
[ordered]@{
  pnp_devices = @($pnps)
  registry_hit = $reg
} | ConvertTo-Json -Compress -Depth 5
"""
    data = _json_from_ps(script, timeout=30.0)
    out: dict[str, Any] = {"source": "wmi-pnp-registry", "detail": data}
    if isinstance(data, dict):
        devs = data.get("pnp_devices") or []
        if isinstance(devs, dict):
            devs = [devs]
        ok = [
            d
            for d in devs
            if isinstance(d, dict)
            and str(d.get("Status", "")).lower() == "ok"
            and (
                str(d.get("Class", "")) == "ComputeAccelerator"
                or "NPU Compute" in str(d.get("FriendlyName", ""))
            )
        ]
        out["present"] = bool(ok or data.get("registry_hit"))
        out["devices"] = devs
    else:
        out["present"] = False
    return out


def _classify_gpus(
    wmi: list[dict[str, Any]], nvidia: list[dict[str, Any]]
) -> dict[str, Any]:
    igpu: list[dict[str, Any]] = []
    dgpu: list[dict[str, Any]] = []
    driving_display: list[str] = []

    for row in wmi:
        name = str(row.get("name") or "")
        low = name.lower()
        is_nvidia = "nvidia" in low
        is_amd_igpu = "amd" in low or "radeon" in low
        if is_nvidia:
            dgpu.append(row)
        elif is_amd_igpu and "microsoft" not in low:
            igpu.append(row)
        elif row.get("current_resolution"):
            driving_display.append(name)

    for row in wmi:
        if row.get("current_resolution"):
            driving_display.append(str(row.get("name") or ""))

    idle_vram_mb = None
    if nvidia:
        idle_vram_mb = nvidia[0].get("vram_used_mb")

    return {
        "integrated": igpu,
        "discrete": dgpu,
        "wmi_all": wmi,
        "display_active_on": sorted({x for x in driving_display if x}),
        "idle_discrete_vram_used_mb": idle_vram_mb,
    }


def collect_inventory(*, write_json: bool = False) -> dict[str, Any]:
    """Full local inventory snapshot. Never raises."""
    t0 = time.time()
    cpu_name_hint = ""
    inv: dict[str, Any] = {
        "collected_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "cpu": {},
        "memory": {},
        "disks": [],
        "nvidia_gpus": [],
        "gpu_layout": {},
        "npu": {},
        "duration_s": 0.0,
    }
    try:
        inv["nvidia_gpus"] = _nvidia_smi_gpus()
    except Exception as exc:  # noqa: BLE001
        inv["nvidia_gpus"] = [{"error": str(exc)}]
    try:
        wmi_vc = _wmi_video_controllers()
        inv["gpu_layout"] = _classify_gpus(wmi_vc, inv["nvidia_gpus"])
    except Exception as exc:  # noqa: BLE001
        inv["gpu_layout"] = {"error": str(exc)}
    try:
        inv["cpu"] = _wmi_cpu()
        cpu_name_hint = str(inv["cpu"].get("name") or "")
        if "780m" in cpu_name_hint.lower() and inv.get("gpu_layout"):
            layout = inv["gpu_layout"]
            if isinstance(layout, dict) and not layout.get("integrated"):
                layout["integrated_cpu_die"] = "AMD Radeon 780M (APU — may be absent from Win32_VideoController when dGPU drives displays)"
                inv["gpu_layout"] = layout
    except Exception as exc:  # noqa: BLE001
        inv["cpu"] = {"error": str(exc)}
    try:
        inv["memory"] = _wmi_memory()
    except Exception as exc:  # noqa: BLE001
        inv["memory"] = {"error": str(exc)}
    try:
        inv["disks"] = _wmi_disks()
    except Exception as exc:  # noqa: BLE001
        inv["disks"] = [{"error": str(exc)}]
    try:
        inv["npu"] = _detect_npu()
    except Exception as exc:  # noqa: BLE001
        inv["npu"] = {"error": str(exc)}
    inv["duration_s"] = round(time.time() - t0, 3)

    if write_json:
        path = hw_data_dir() / "inventory.json"
        path.write_text(json.dumps(inv, indent=2), encoding="utf-8")
    return inv


def inventory_summary_for_panel(inv: dict[str, Any] | None = None) -> dict[str, Any]:
    """Compact slice for /api/perf and health UI."""
    inv = inv or collect_inventory()
    ng = inv.get("nvidia_gpus") or []
    g0 = ng[0] if ng and isinstance(ng[0], dict) else {}
    layout = inv.get("gpu_layout") or {}
    cpu = inv.get("cpu") or {}
    mem = inv.get("memory") or {}
    return {
        "cpu_name": cpu.get("name"),
        "cpu_cores": cpu.get("cores"),
        "ram_total_gb": mem.get("total_physical_gb"),
        "ram_free_gb": mem.get("free_physical_gb"),
        "gpu_name": g0.get("name"),
        "vram_used_mb": g0.get("vram_used_mb"),
        "vram_total_mb": g0.get("vram_total_mb"),
        "gpu_temp_c": g0.get("temp_c"),
        "gpu_power_w": g0.get("power_draw_w"),
        "display_on": layout.get("display_active_on"),
        "npu_present": (inv.get("npu") or {}).get("present"),
    }
