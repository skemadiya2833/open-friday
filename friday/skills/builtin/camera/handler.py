"""One-shot webcam description — requires camera enabled + brief arm for the look."""

from __future__ import annotations

import re
import tempfile
import time
import webbrowser
from pathlib import Path

from friday.skills.base import Skill, SkillContext, SkillManifest, SkillResult

_SHOW_FRAME = re.compile(
    r"\b(show|open|display|pull up|bring up)\b.{"
    r"0,80}\b(camera|webcam|what you('?re| are) seeing|feed|preview|view)\b|"
    r"\b(show|open)\b.{"
    r"0,40}\b(what .{0,20}see)\b",
    re.I,
)


def _open_camera_frame_window(jpeg_b64: str, *, width: int = 0, height: int = 0) -> Path | None:
    """Open the captured frame in the default browser so the owner can see it."""
    try:
        html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Friday — Camera</title>
<style>
  body {{ margin:0; background:#0b1220; color:#e8eef9; font-family:Segoe UI,system-ui,sans-serif;
         display:flex; flex-direction:column; align-items:center; min-height:100vh; padding:1.5rem; }}
  .eyebrow {{ color:#3ecbff; font-size:.72rem; letter-spacing:.16em; text-transform:uppercase; }}
  h1 {{ margin:.35rem 0 1rem; font-weight:600; font-size:1.2rem; }}
  img {{ max-width:min(960px,100%); height:auto; border:1px solid #1e2a44; background:#000; }}
  p {{ color:#8fa3c4; font-size:.85rem; }}
</style></head><body>
  <div class="eyebrow">Friday · webcam</div>
  <h1>What I'm seeing</h1>
  <img src="data:image/jpeg;base64,{jpeg_b64}" alt="Webcam frame"
       width="{width or ''}" height="{height or ''}"/>
  <p>One frame · not stored · safe to close</p>
</body></html>"""
        path = Path(tempfile.gettempdir()) / f"friday-camera-{int(time.time())}.html"
        path.write_text(html, encoding="utf-8")
        webbrowser.open(path.as_uri())
        return path
    except Exception:  # noqa: BLE001
        return None


class SkillHandler(Skill):
    manifest = SkillManifest(
        id="camera",
        name="Camera Look",
        description="Describe what the local webcam sees",
        requires_vision=True,
        priority=92,
    )

    def run(self, ctx: SkillContext) -> SkillResult:
        from friday.camera.capture import capture_jpeg_b64
        from friday.camera.describe import describe_camera
        from friday.camera.session import camera_feature_enabled, get_camera_session
        from friday.models.manager import get_model_manager

        if not camera_feature_enabled():
            reply = (
                "Camera sensing is off. Turn on **Enable camera** in Systems "
                "(or set `FRIDAY_CAMERA=on`), install "
                "`pip install -r requirements/camera.lock.txt`, restart Friday, then ask again."
            )
            return SkillResult(reply=reply, skill_id="camera")

        session = get_camera_session()
        st = session.status()
        if not st.opencv:
            return SkillResult(
                reply="OpenCV is missing for webcam capture. Run `pip install -r requirements/camera.lock.txt` and restart.",
                skill_id="camera",
            )
        # Brief auto-arm for a look request so "show me what you see" just works.
        if not session.is_armed():
            armed = session.arm(ttl=90)
            if not armed.get("ok") or not session.is_armed():
                return SkillResult(
                    reply=(
                        armed.get("error")
                        or "Couldn't arm the camera. Open Systems → **Enable camera** / **Arm camera**, then ask again."
                    ),
                    skill_id="camera",
                )

        want_show = bool(_SHOW_FRAME.search(ctx.message or "")) or bool(
            re.search(r"\b(show|open|display|preview|feed|through)\b", ctx.message or "", re.I)
        )

        get_model_manager().ensure_loaded("vision")
        ctx.emit("status", {"status": "thinking"})
        ctx.emit("activity", {"step": "capture", "message": "Opening webcam for one frame…"})
        # Keep HUD "CAMERA LIVE" on through capture + describe (capture alone is too brief).
        ctx.emit("camera", {"live": True, "phase": "capture"})
        session.set_live(True)
        try:
            shot = capture_jpeg_b64()
            if not shot.ok or not shot.jpeg_b64:
                reply = shot.error or "I couldn't capture from the webcam. Check the device and try again."
                return SkillResult(reply=reply, skill_id="camera", metadata=shot.to_dict())

            try:
                from friday.safety.audit import get_audit_log

                get_audit_log().record(
                    tool="camera_snap",
                    args={"width": shot.width, "height": shot.height, "bytes": shot.bytes_len},
                    outcome="ok",
                    risk="confirm",
                    caller="skill:camera",
                    detail=f"duration_ms={shot.duration_ms}",
                )
            except Exception:  # noqa: BLE001
                pass

            # Show the frame in Control Center + optional browser window.
            ctx.emit("camera_frame", {
                "jpeg_b64": shot.jpeg_b64,
                "width": shot.width,
                "height": shot.height,
            })
            opened = None
            if want_show:
                ctx.emit("activity", {"step": "show", "message": "Opening camera frame in browser…"})
                opened = _open_camera_frame_window(
                    shot.jpeg_b64, width=shot.width, height=shot.height,
                )

            ctx.emit("observation", {"source": "camera", "size": [shot.width, shot.height]})
            ctx.emit("camera", {"live": True, "phase": "describe"})
            ctx.emit("activity", {
                "step": "describe",
                "message": f"Describing webcam frame ({shot.width}×{shot.height})…",
            })

            reply = describe_camera(
                ctx.message,
                frame_b64=shot.jpeg_b64,
                on_token=lambda t: ctx.emit("skill_token", {"text": t}),
                voice_mode=ctx.voice_mode,
            )
            # Drop reference ASAP (GC); never persist the frame.
            from friday.camera.session import camera_backend, camera_index

            cam_idx = camera_index()
            cam_be = camera_backend()
            cam_label = f"{cam_be}:{cam_idx}" if cam_be else f"index {cam_idx}"
            frame_meta = {
                "source": "camera",
                "opened_browser": bool(opened),
                "width": shot.width,
                "height": shot.height,
                "camera_index": cam_idx,
                "camera_backend": cam_be,
            }
            del shot
            if not (reply or "").strip():
                reply = "I captured a webcam frame but couldn't describe it. Please try again."
            else:
                from friday.humor import maybe_append_quip

                reply = maybe_append_quip(
                    reply.strip(),
                    user_text=ctx.message,
                    context="camera",
                )
            reply = f"(Using camera {cam_label})\n\n{reply.strip()}"
            if opened:
                reply = f"{reply}\n\n(Opened the camera frame in your browser.)"
            return SkillResult(
                reply=reply.strip(),
                skill_id="camera",
                metadata=frame_meta,
            )
        finally:
            session.set_live(False)
            ctx.emit("camera", {"live": False})
