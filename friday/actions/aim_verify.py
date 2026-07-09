"""Aim → verify → adjust before precise pointer actions."""

from __future__ import annotations

import time

from friday.actions.catalog import AIM_ACTIONS
from friday.actions.coordinates import (
    image_point_to_model,
    image_to_native,
    model_point_to_image,
    native_to_image,
)
from friday.config import (
    AIM_VERIFY_ENABLED,
    AIM_VERIFY_MAX_ROUNDS,
    AIM_VERIFY_SETTLE_MS,
    AIM_VERIFY_STRICT,
    OVERLAY_ENABLED,
)
from friday.types import ActionStep


def _coords_close(x1: int, y1: int, x2: int, y2: int, tol: int = 8) -> bool:
    return abs(x1 - x2) <= tol and abs(y1 - y2) <= tol


def refine_aim(
    step: ActionStep,
    feed,
    native_size: tuple[int, int],
    image_size: tuple[int, int],
) -> ActionStep:
    if not AIM_VERIFY_ENABLED or feed is None:
        return step
    if step.action.upper() not in AIM_ACTIONS or step.x is None or step.y is None:
        return step

    from friday.models.local import query_aim_verification
    from friday.ui.click_marker import confirm_click_target, hide_aim_cursor, show_aim_cursor

    action = step.action.upper()
    description = step.description or action
    native_x, native_y = int(step.x), int(step.y)
    img_x = step.extras.get("_model_x")
    img_y = step.extras.get("_model_y")
    if img_x is None or img_y is None:
        img_x, img_y = native_to_image(native_x, native_y, native_size, image_size)
    else:
        img_x, img_y = int(img_x), int(img_y)

    print(f"[Aim] Verifying {action} target ({native_x}, {native_y}) ...")
    if OVERLAY_ENABLED:
        from friday.ui import overlay
        overlay.set_status("aiming")

    # Live feed is already paused by the agent loop during decide+act.
    keep_cursor = False
    data = step.to_dict()
    try:
        for attempt in range(1, AIM_VERIFY_MAX_ROUNDS + 1):
            state = "aim" if attempt == 1 else "adjust"
            show_aim_cursor(native_x, native_y, step=data, state=state)
            time.sleep(AIM_VERIFY_SETTLE_MS / 1000.0)

            # capture_for_aim_verify hides Win32 cursor and draws marker in PIL.
            packet = feed.capture_for_aim_verify(
                native_x, native_y, state=state, label=description,
            )
            model_x, model_y = image_point_to_model(img_x, img_y, packet.image_size)
            result = query_aim_verification(
                target_description=description,
                action=action,
                image_x=model_x,
                image_y=model_y,
                image_size=packet.image_size,
                frame_b64=packet.base64_png,
                attempt=attempt,
            )

            # Returned coords are in model space — convert to image pixels.
            if result.get("x") is not None and result.get("y") is not None:
                rx, ry = model_point_to_image(
                    int(result["x"]), int(result["y"]), packet.image_size,
                )
                result["x"], result["y"] = rx, ry

            if result.get("verified") or (
                result.get("x") is not None
                and result.get("y") is not None
                and _coords_close(int(result["x"]), int(result["y"]), img_x, img_y)
            ):
                print(f"[Aim] Verified on attempt {attempt}.")
                confirm_click_target(native_x, native_y, step=data)
                time.sleep(0.2)
                keep_cursor = True
                return _refined(step, native_x, native_y, img_x, img_y)

            adj_x, adj_y = result.get("x"), result.get("y")
            reason = result.get("reason", "")
            if adj_x is not None and adj_y is not None:
                img_x, img_y = int(adj_x), int(adj_y)
                native_x, native_y = image_to_native(img_x, img_y, packet.image_size, native_size)
                print(
                    f"[Aim] Attempt {attempt}: adjusting → image ({img_x}, {img_y}) "
                    f"native ({native_x}, {native_y})"
                    + (f" — {reason}" if reason else "")
                )
                data = step.to_dict()
                data["x"], data["y"] = native_x, native_y
                # Keep iterating: move the marker and re-check until it lands.
                continue

            # Not verified and the model gave no correction. Keep trying a few
            # rounds (sampling varies) rather than giving up immediately.
            print(
                f"[Aim] Attempt {attempt}: not verified"
                + (f": {reason}" if reason else "")
                + (" — retrying" if attempt < AIM_VERIFY_MAX_ROUNDS else "")
            )

        # Rounds exhausted without verification.
        if AIM_VERIFY_STRICT:
            print(
                f"[Aim] Target '{description}' not verified after "
                f"{AIM_VERIFY_MAX_ROUNDS} rounds — aborting to avoid a misclick."
            )
            aborted = _refined(step, native_x, native_y, img_x, img_y)
            aborted.extras["_aim_verified"] = False
            aborted.extras["_aim_abort"] = True
            return aborted

        print(f"[Aim] Using best-effort aim ({native_x}, {native_y}) — unverified.")
        confirm_click_target(native_x, native_y, step=data)
        time.sleep(0.15)
        keep_cursor = True
        refined = _refined(step, native_x, native_y, img_x, img_y)
        refined.extras["_aim_verified"] = False
        return refined
    finally:
        if not keep_cursor:
            hide_aim_cursor(wait=True)
        if OVERLAY_ENABLED:
            from friday.ui import overlay
            overlay.set_status("running")


def _refined(
    step: ActionStep, native_x: int, native_y: int, img_x: int, img_y: int,
) -> ActionStep:
    refined = ActionStep.from_dict(step.to_dict())
    refined.x = native_x
    refined.y = native_y
    refined.extras["_model_x"] = img_x
    refined.extras["_model_y"] = img_y
    refined.extras["_aim_verified"] = True
    return refined
