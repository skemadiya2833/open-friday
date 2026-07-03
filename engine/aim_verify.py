"""
Aim → verify (live stream) → adjust → click loop.

Shows an on-screen aim cursor, captures a fresh frame with the crosshair composited
into the image (layered Win32 overlays are invisible to mss), asks the VLM if the
aim is on the right target, adjusts if not, then clicks.
"""

from __future__ import annotations

import time

from config import (
    AIM_VERIFY_ENABLED,
    AIM_VERIFY_MAX_ROUNDS,
    AIM_VERIFY_SETTLE_MS,
    OVERLAY_ENABLED,
)
from engine.click_marker import confirm_click_target, hide_aim_cursor, show_aim_cursor
from engine.local_model import query_aim_verification
from engine.stream import LiveScreenFeed

if OVERLAY_ENABLED:
    from engine import overlay

_COORD_ACTIONS = frozenset({
    "CLICK", "DOUBLE_CLICK", "RIGHT_CLICK", "MIDDLE_CLICK", "HOVER", "SCROLL",
})

_AIM_STATE_CYCLE = ("aim", "adjust")


def _native_to_image(
    x: int, y: int, native_size: tuple[int, int], image_size: tuple[int, int],
) -> tuple[int, int]:
    nw, nh = native_size
    iw, ih = image_size
    if (nw, nh) == (iw, ih):
        return x, y
    return int(round(x * iw / nw)), int(round(y * ih / nh))


def _image_to_native(
    x: int, y: int, native_size: tuple[int, int], image_size: tuple[int, int],
) -> tuple[int, int]:
    nw, nh = native_size
    iw, ih = image_size
    if (nw, nh) == (iw, ih):
        return x, y
    return int(round(x * nw / iw)), int(round(y * nh / ih))


def _step_needs_aim(step: dict) -> bool:
    action = str(step.get("action", "")).upper()
    if action not in _COORD_ACTIONS:
        return False
    return step.get("x") is not None and step.get("y") is not None


def _coords_close(x1: int, y1: int, x2: int, y2: int, tol: int = 8) -> bool:
    return abs(x1 - x2) <= tol and abs(y1 - y2) <= tol


def refine_step_with_live_verification(
    step: dict,
    feed: LiveScreenFeed | None,
    native_size: tuple[int, int],
    image_size: tuple[int, int],
) -> dict:
    """
    For coordinate actions: show aim cursor, verify via live stream, adjust, return
    refined step. Non-coordinate steps pass through unchanged.
    """
    if not AIM_VERIFY_ENABLED or feed is None or not _step_needs_aim(step):
        return step

    action = str(step["action"]).upper()
    description = str(step.get("description") or step.get("message") or action)
    native_x, native_y = int(step["x"]), int(step["y"])
    img_x = step.get("_model_x")
    img_y = step.get("_model_y")
    if img_x is None or img_y is None:
        img_x, img_y = _native_to_image(native_x, native_y, native_size, image_size)
    else:
        img_x, img_y = int(img_x), int(img_y)

    print(f"[Aim] Verifying {action} target ({native_x}, {native_y}) ...")
    if OVERLAY_ENABLED:
        overlay.set_status("aiming")

    keep_cursor = False
    try:
        for attempt in range(1, AIM_VERIFY_MAX_ROUNDS + 1):
            state = _AIM_STATE_CYCLE[min(attempt - 1, 1)]
            show_aim_cursor(native_x, native_y, step=step, state=state)
            time.sleep(AIM_VERIFY_SETTLE_MS / 1000.0)

            packet = feed.capture_for_aim_verify(
                native_x, native_y, state=state, label=description,
            )
            frame_b64 = packet.base64_png
            image_size = packet.image_size
            if not frame_b64:
                break

            result = query_aim_verification(
                target_description=description,
                action=action,
                image_x=img_x,
                image_y=img_y,
                image_size=image_size,
                frame_b64=frame_b64,
                attempt=attempt,
            )

            if result.get("verified"):
                print(f"[Aim] Verified on attempt {attempt}.")
                confirm_click_target(native_x, native_y, step=step)
                time.sleep(0.2)
                refined = dict(step)
                refined["x"] = native_x
                refined["y"] = native_y
                refined["_model_x"] = img_x
                refined["_model_y"] = img_y
                refined["_aim_verified"] = True
                keep_cursor = True
                return refined

            adj_x = result.get("x")
            adj_y = result.get("y")
            reason = result.get("reason", "")
            if adj_x is not None and adj_y is not None:
                adj_x, adj_y = int(adj_x), int(adj_y)
                if _coords_close(adj_x, adj_y, img_x, img_y):
                    print(f"[Aim] Target confirmed (coords unchanged) on attempt {attempt}.")
                    confirm_click_target(native_x, native_y, step=step)
                    time.sleep(0.2)
                    refined = dict(step)
                    refined["x"] = native_x
                    refined["y"] = native_y
                    refined["_model_x"] = img_x
                    refined["_model_y"] = img_y
                    refined["_aim_verified"] = True
                    keep_cursor = True
                    return refined

                img_x, img_y = adj_x, adj_y
                native_x, native_y = _image_to_native(img_x, img_y, native_size, image_size)
                print(
                    f"[Aim] Adjusting → image ({img_x}, {img_y}) native ({native_x}, {native_y})"
                    + (f" — {reason}" if reason else "")
                )
                step = dict(step)
                step["x"] = native_x
                step["y"] = native_y
                step["_model_x"] = img_x
                step["_model_y"] = img_y
                continue

            print(f"[Aim] Not verified, no adjustment returned" + (f": {reason}" if reason else ""))
            break

        print(f"[Aim] Proceeding with best aim ({native_x}, {native_y}).")
        confirm_click_target(native_x, native_y, step=step)
        time.sleep(0.15)
        refined = dict(step)
        refined["x"] = native_x
        refined["y"] = native_y
        refined["_model_x"] = img_x
        refined["_model_y"] = img_y
        refined["_aim_verified"] = True
        keep_cursor = True
        return refined

    finally:
        if not keep_cursor:
            hide_aim_cursor()
        if OVERLAY_ENABLED and feed.is_running:
            overlay.set_status("live")
