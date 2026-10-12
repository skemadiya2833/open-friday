"""One-shot webcam description — requires FRIDAY_CAMERA=on and an owner arm grant."""

from __future__ import annotations

from friday.skills.base import Skill, SkillContext, SkillManifest, SkillResult


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
                "Camera sensing is off. Set `FRIDAY_CAMERA=on` in `.env`, install "
                "`pip install -r requirements/camera.lock.txt`, restart Friday, then Arm Camera in Systems."
            )
            return SkillResult(reply=reply, skill_id="camera")

        session = get_camera_session()
        st = session.status()
        if not st.opencv:
            return SkillResult(
                reply="OpenCV is missing for webcam capture. Run `pip install -r requirements/camera.lock.txt` and restart.",
                skill_id="camera",
            )
        if not session.is_armed():
            return SkillResult(
                reply=(
                    "Camera is not armed. Open Systems in the Control Center, turn on "
                    "**Arm camera**, then ask again. E-stop (Ctrl+Alt+F12) disarms it anytime."
                ),
                skill_id="camera",
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
            return SkillResult(
                reply=reply.strip(),
                skill_id="camera",
                metadata={"source": "camera"},
            )
        finally:
            session.set_live(False)
            ctx.emit("camera", {"live": False})
