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
def _reset_camera(monkeypatch):
    monkeypatch.delenv("FRIDAY_CAMERA", raising=False)
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


def test_skill_refuses_when_disarmed(monkeypatch):
    monkeypatch.setenv("FRIDAY_CAMERA", "on")
    reset_camera_session_for_tests()
    from friday.skills.base import SkillContext
    from friday.skills.builtin.camera.handler import SkillHandler

    ctx = SkillContext(message="what am I looking at?", session_id="t", history=[])
    with patch("friday.camera.capture.opencv_available", return_value=True):
        result = SkillHandler().run(ctx)
    assert result.skill_id == "camera"
    assert "not armed" in result.reply.lower() or "Arm" in result.reply


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
    assert result.reply.startswith("A desk lamp.")
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
