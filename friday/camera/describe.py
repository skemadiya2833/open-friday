"""Describe a webcam frame with the local vision model. Frames never leave the machine via this path."""

from __future__ import annotations

from collections.abc import Callable

from friday.prompts import camera_user_prompt


def fence_camera_prompt(question: str) -> str:
    """Prompt that treats the attached image as untrusted CAMERA_DATA."""
    return camera_user_prompt(question, voice_mode=False)


def describe_camera(
    question: str,
    *,
    frame_b64: str,
    on_token: Callable[[str], None] | None = None,
    voice_mode: bool = False,
) -> str:
    """Answer a question about a webcam JPEG (base64) using the local VLM."""
    from friday.config import CHAT_NUM_CTX, CHAT_NUM_PREDICT
    from friday.models.local import _stream_chat
    from friday.models.manager import get_model_manager

    mm = get_model_manager()
    vision_tag = mm.ensure_loaded("vision")
    prompt = camera_user_prompt(question, voice_mode=voice_mode)
    predict = 96 if voice_mode else min(384, CHAT_NUM_PREDICT + 128)
    image = frame_b64
    messages = [{"role": "user", "content": prompt, "images": [image]}]
    accumulated = ""
    try:
        accumulated, _ = _stream_chat(
            messages,
            reasoning_mode=False,
            think=False,
            model=vision_tag,
            num_predict=predict,
            num_ctx=CHAT_NUM_CTX,
            on_token=on_token,
        )
    except RuntimeError as exc:
        from friday.persona import owner_name

        return f"Couldn't read the camera, {owner_name()} ({exc})."
    finally:
        messages[0].pop("images", None)
        image = ""
        try:
            mm.after_vision()
        except Exception:  # noqa: BLE001
            pass
    return (accumulated or "").strip()
