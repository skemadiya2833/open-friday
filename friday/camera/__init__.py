"""Opt-in local webcam sensing (privacy-first). Off unless FRIDAY_CAMERA=on."""

from __future__ import annotations

from friday.camera.session import get_camera_session

__all__ = ["get_camera_session"]
