"""Camera v1 — arm grant, e-stop disarm, intent routing, mocked capture (no hardware)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from friday.assistant.intent import Intent, apply_policy
from friday.camera.capture import CaptureResult
from friday.camera.describe import fence_camera_prompt
from friday.camera.session import (
    get_camera_session,
    reset_camera_session_for_tests,
)


@pytest.fixture(autouse=True)
def _reset_camera(monkeypatch, tmp_path):
    monkeypatch.delenv("FRIDAY_CAMERA", raising=False)
    monkeypatch.setattr("friday.config.DATA_DIR", str(tmp_path))
    reset_camera_session_for_tests()
    yield
    reset_camera_session_for_tests()


def test_camera_off_by_default_cannot_arm(monkeypatch):
    monkeypatch.setenv("FRIDAY_CAMERA", "off")
    reset_camera_session_for_tests()
    out = get_camera_session().arm()
    assert out["ok"] is False
    assert not get_camera_session().is_armed()


def test_arm_disarm_and_ttl(monkeypatch):
    monkeypatch.setenv("FRIDAY_CAMERA", "on")
    reset_camera_session_for_tests()
    s = get_camera_session()
    assert s.arm(ttl=60)["ok"] is True
    assert s.is_armed()
    st = s.status()
    assert st.enabled and st.armed
    assert s.disarm(reason="test")["ok"] is True
    assert not s.is_armed()


def test_estop_disarms_camera(monkeypatch):
    monkeypatch.setenv("FRIDAY_CAMERA", "on")
    reset_camera_session_for_tests()
    get_camera_session().arm(ttl=120)
    assert get_camera_session().is_armed()
    from friday.safety.estop import emergency_stop

    emergency_stop("test", stop_mcp=False)
    assert not get_camera_session().is_armed()


def test_capture_requires_arm(monkeypatch):
    monkeypatch.setenv("FRIDAY_CAMERA", "on")
    reset_camera_session_for_tests()
    from friday.camera.capture import capture_jpeg_b64

    shot = capture_jpeg_b64()
    assert not shot.ok
    assert "armed" in shot.error.lower()


def test_skill_refuses_when_camera_off(monkeypatch):
    monkeypatch.setenv("FRIDAY_CAMERA", "off")
    reset_camera_session_for_tests()
    from friday.skills.base import SkillContext
    from friday.skills.builtin.camera.handler import SkillHandler

    ctx = SkillContext(message="what am I looking at?", session_id="t", history=[])
    with patch("friday.camera.capture.opencv_available", return_value=True):
        result = SkillHandler().run(ctx)
    assert result.skill_id == "camera"
    assert "off" in result.reply.lower() or "enable" in result.reply.lower()


def test_skill_auto_arms_when_enabled(monkeypatch):
    monkeypatch.setenv("FRIDAY_CAMERA", "on")
    reset_camera_session_for_tests()
    from friday.skills.base import SkillContext
    from friday.skills.builtin.camera.handler import SkillHandler

    fake = CaptureResult(ok=True, jpeg_b64="AAAA", width=64, height=48, bytes_len=4)
    ctx = SkillContext(message="what am I looking at?", session_id="t", history=[])
    with (
        patch("friday.camera.capture.opencv_available", return_value=True),
        patch("friday.camera.capture.capture_jpeg_b64", return_value=fake),
        patch("friday.camera.describe.describe_camera", return_value="A lamp."),
        patch("friday.models.manager.get_model_manager") as mm,
    ):
        mm.return_value.ensure_loaded = lambda *_a, **_k: None
        result = SkillHandler().run(ctx)
    assert result.skill_id == "camera"
    assert "lamp" in result.reply.lower()
    assert get_camera_session().is_armed()


def test_skill_snap_uses_mock_capture(monkeypatch):
    monkeypatch.setenv("FRIDAY_CAMERA", "on")
    reset_camera_session_for_tests()
    get_camera_session().arm(ttl=120)

    fake = CaptureResult(
        ok=True,
        jpeg_b64="AAAA",
        width=64,
        height=48,
        bytes_len=4,
        duration_ms=1.0,
    )
    from friday.skills.base import SkillContext
    from friday.skills.builtin.camera.handler import SkillHandler

    events: list[tuple[str, dict]] = []
    ctx = SkillContext(
        message="what am I looking at?",
        session_id="t",
        history=[],
        emit=lambda t, d: events.append((t, d)),
    )
    with (
        patch("friday.camera.capture.opencv_available", return_value=True),
        patch("friday.camera.capture.capture_jpeg_b64", return_value=fake),
        patch("friday.camera.describe.describe_camera", return_value="A desk lamp."),
        patch("friday.models.manager.get_model_manager") as mm,
    ):
        mm.return_value.ensure_loaded = lambda *_a, **_k: None
        result = SkillHandler().run(ctx)
    assert "A desk lamp." in result.reply
    assert "camera" in result.reply.lower()
    assert result.skill_id == "camera"
    cam_events = [d for t, d in events if t == "camera"]
    assert any(d.get("live") is True for d in cam_events)
    assert cam_events[-1].get("live") is False
    assert not get_camera_session().is_live()


def test_fence_mentions_camera_data():
    text = fence_camera_prompt("what is this?")
    assert "CAMERA_DATA" in text or "camera" in text.lower()
    assert "BEGIN_UNTRUSTED_DATA" in text


def test_intent_camera_vs_observe():
    cam = apply_policy(
        Intent(mode="act", skill_id="computer_use", confidence=0.9, objective="x", reason="t"),
        "what am I looking at?",
    )
    assert cam.skill_id == "camera" and cam.mode == "look"

    scr = apply_policy(
        Intent(mode="act", skill_id="computer_use", confidence=0.9, objective="x", reason="t"),
        "what's on my screen?",
    )
    assert scr.skill_id == "observe" and scr.mode == "look"


def test_deterministic_classify_camera(monkeypatch):
    monkeypatch.setenv("FRIDAY_CAMERA", "on")
    # classify_intent may call LLM; use deterministic path via message that hits _deterministic_intent
    from friday.assistant import intent as intent_mod

    got = intent_mod._deterministic_intent("what am I looking at?")
    assert got is not None
    assert got.skill_id == "camera"

    got2 = intent_mod._deterministic_intent("what's on my screen?")
    assert got2 is not None
    assert got2.skill_id == "observe"

    got3 = intent_mod._deterministic_intent("show me what you're seeing through my camera")
    assert got3 is not None
    assert got3.skill_id == "camera"


def test_camera_prefs_override_env(monkeypatch, tmp_path):
    monkeypatch.setenv("FRIDAY_CAMERA", "on")
    monkeypatch.setenv("FRIDAY_CAMERA_INDEX", "0")
    monkeypatch.setattr("friday.config.DATA_DIR", str(tmp_path))
    from friday.camera import devices as cam_dev
    from friday.camera.session import camera_feature_enabled, camera_index, reset_camera_session_for_tests

    reset_camera_session_for_tests()
    assert camera_index() == 0
    out = cam_dev.save_selected_index(2)
    assert out["ok"] and out["index"] == 2
    assert camera_index() == 2
    assert (tmp_path / "camera_prefs.json").is_file()

    monkeypatch.setenv("FRIDAY_CAMERA", "off")
    assert camera_feature_enabled() is False
    cam_dev.save_camera_enabled(True)
    assert camera_feature_enabled() is True
    cam_dev.save_camera_enabled(False)
    assert camera_feature_enabled() is False


def test_list_cameras_mocked(monkeypatch):
    from friday.camera import devices as cam_dev
    from friday.camera.devices import CameraDevice

    fake = [
        CameraDevice(index=0, name="Integrated Webcam", width=1280, height=720),
        CameraDevice(index=1, name="USB Camera", width=640, height=480),
    ]
    monkeypatch.setattr(cam_dev, "list_cameras", lambda **_k: fake)
    monkeypatch.setattr("friday.camera.capture.opencv_available", lambda: True)
    monkeypatch.setenv("FRIDAY_CAMERA", "on")
    payload = cam_dev.devices_payload()
    assert payload["ok"] and payload["count"] == 2
    assert payload["devices"][0]["name"] == "Integrated Webcam"
    assert "0" in payload["devices"][0]["label"]
    assert payload["devices"][0].get("key")


def test_list_cameras_stops_after_consecutive_misses(monkeypatch):
    """Do not keep probing past the last device (avoids FFmpeg index-out-of-range spam)."""
    from friday.camera import devices as cam_dev

    calls: list[tuple[str, int]] = []

    def fake_probe(backend, api, *, limit):
        for i in range(min(2, limit)):
            calls.append((backend, i))
        return []

    monkeypatch.setattr("friday.camera.capture.opencv_available", lambda: True)
    # Force OpenCV probe path (skip live ffmpeg DirectShow enumeration).
    monkeypatch.setattr(cam_dev, "_list_cameras_ffmpeg_first", lambda: None)
    monkeypatch.setattr(cam_dev, "_windows_friendly_names", lambda: [])
    monkeypatch.setattr(cam_dev, "_backend_apis", lambda: [("msmf", 0), ("dshow", 1)])
    monkeypatch.setattr(cam_dev, "_probe_backend", fake_probe)
    monkeypatch.setattr(cam_dev, "_silence_opencv_logs", lambda: None)
    monkeypatch.setattr(cam_dev, "_restore_opencv_logs", lambda _p: None)
    monkeypatch.setattr(cam_dev, "_match_ffmpeg_names", lambda _devs: None)
    try:
        import cv2  # noqa: F401
    except Exception:
        return
    out = cam_dev.list_cameras(max_index=8)
    assert out == []
    # Each backend probes until two consecutive misses (indices 0,1).
    assert calls == [("msmf", 0), ("msmf", 1), ("dshow", 0), ("dshow", 1)]


def test_save_selected_stores_backend(monkeypatch, tmp_path):
    monkeypatch.setattr("friday.config.DATA_DIR", str(tmp_path))
    from friday.camera import devices as cam_dev
    from friday.camera.session import camera_backend, camera_index, reset_camera_session_for_tests

    reset_camera_session_for_tests()
    out = cam_dev.save_selected_index(1, backend="dshow")
    assert out["ok"] and out["backend"] == "dshow"
    assert camera_index() == 1
    assert camera_backend() == "dshow"


def test_preview_auto_arms_when_enabled(monkeypatch, tmp_path):
    """GET /api/camera/preview must not 403 when enabled but disarmed."""
    monkeypatch.setenv("FRIDAY_CAMERA", "on")
    monkeypatch.setattr("friday.config.DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FRIDAY_AUTH", "off")
    reset_camera_session_for_tests()
    assert not get_camera_session().is_armed()

    fake = CaptureResult(ok=True, jpeg_b64="AAAA", width=64, height=48, bytes_len=4)
    from fastapi.testclient import TestClient
    from friday.server.app import app

    with (
        patch("friday.camera.capture.capture_jpeg_b64", return_value=fake),
        TestClient(app, base_url="http://127.0.0.1:8787") as client,
    ):
        res = client.get("/api/camera/preview")
    assert res.status_code == 200, res.text
    assert res.headers.get("content-type", "").startswith("image/jpeg")
    assert get_camera_session().is_armed()


def test_preview_rejects_when_camera_off(monkeypatch, tmp_path):
    monkeypatch.setenv("FRIDAY_CAMERA", "off")
    monkeypatch.setattr("friday.config.DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FRIDAY_AUTH", "off")
    reset_camera_session_for_tests()
    from fastapi.testclient import TestClient
    from friday.server.app import app

    with TestClient(app, base_url="http://127.0.0.1:8787") as client:
        res = client.get("/api/camera/preview")
    assert res.status_code == 400
    assert "off" in res.json().get("detail", "").lower()
