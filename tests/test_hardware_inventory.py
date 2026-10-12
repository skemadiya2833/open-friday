"""Hardware inventory and perf panel integration (mocked / skip-friendly)."""

from __future__ import annotations

import json
import sys
from unittest import mock

import pytest

from friday.diagnostics.hardware import collect_inventory, inventory_summary_for_panel
from friday.perf import snapshot, thermal_advice, GpuSample


def test_collect_inventory_never_raises():
    inv = collect_inventory()
    assert "platform" in inv
    assert "cpu" in inv
    assert "nvidia_gpus" in inv


def test_inventory_summary_from_fixture():
    inv = {
        "cpu": {"name": "Test CPU", "cores": 8},
        "memory": {"total_physical_gb": 32, "free_physical_gb": 16},
        "nvidia_gpus": [{"name": "Test GPU", "vram_used_mb": 100, "vram_total_mb": 16000, "temp_c": 55}],
        "gpu_layout": {"display_active_on": ["Test GPU"]},
        "npu": {"present": False},
    }
    s = inventory_summary_for_panel(inv)
    assert s["cpu_name"] == "Test CPU"
    assert s["gpu_name"] == "Test GPU"
    assert s["vram_total_mb"] == 16000


def test_thermal_advice_high_temp():
    tips = thermal_advice(GpuSample(temp_c=88, vram_used_mb=100, vram_total_mb=16000))
    assert any("85" in t for t in tips)


@pytest.mark.skipif(sys.platform != "win32", reason="WMI inventory is Windows-first")
def test_wmi_path_with_mock_ps():
    fake = json.dumps({"name": "Mock CPU", "cores": 4, "logical_processors": 8})
    with mock.patch(
        "friday.diagnostics.hardware._run_ps",
        return_value=(fake, "", 0),
    ):
        inv = collect_inventory()
    assert inv["cpu"].get("name") == "Mock CPU"


def test_snapshot_includes_hardware_keys():
    snap = snapshot()
    assert "gpu_now" in snap
    assert "hardware" in snap
    assert "thermal_advice" in snap
    assert "resource_policy" in snap


def test_resource_policy_keep_alive_defaults():
    from friday.runtime.resource_policy import keep_alive_for_role

    assert keep_alive_for_role("coder") == 0 or keep_alive_for_role("coder") == "0"
