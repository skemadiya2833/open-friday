import json

from friday.experimental import sensors as S
from friday.tools.registry import reset_registry
from friday.tools.types import ToolRisk


def test_sensors_are_read_only_safe_and_shaped():
    d = S.read_all()
    assert 0 <= d["cpu_load_percent"] <= 100
    assert d["memory"]["total_gb"] > 0
    json.dumps(d)                                  # serialisable
    (spec,) = S.sensor_specs()
    assert spec.risk == ToolRisk.SAFE and spec.source == "experimental"


def test_tool_not_registered_by_default(isolated, monkeypatch):
    monkeypatch.delenv("FRIDAY_SENSORS", raising=False)
    reset_registry()
    from friday.tools.registry import get_registry
    assert get_registry().get("system_sensors") is None


def test_tool_registered_when_enabled(isolated, monkeypatch):
    monkeypatch.setenv("FRIDAY_SENSORS", "true")
    reset_registry()
    from friday.tools.registry import get_registry
    reg = get_registry()
    assert reg.get("system_sensors") is not None
    assert "cpu_load_percent" in reg.call("system_sensors", {}).text()
    reset_registry()


def test_lhm_unreachable_is_none():
    assert S.lhm_temperatures("http://127.0.0.1:1/data.json") is None
