"""One-shot screen description — no mouse/keyboard actions."""

from __future__ import annotations

from friday.skills.base import Skill, SkillContext, SkillManifest, SkillResult


class SkillHandler(Skill):
    manifest = SkillManifest(
        id="observe",
        name="Observe Screen",
        description="Describe the desktop from a screenshot",
        requires_vision=True,
        priority=90,
    )

    def run(self, ctx: SkillContext) -> SkillResult:
        from friday.models.local import describe_screen
        from friday.models.manager import get_model_manager
        from friday.vision.feed import LiveScreenFeed

        get_model_manager().ensure_loaded("vision")
        ctx.emit("status", {"status": "thinking"})
        ctx.emit("activity", {"step": "capture", "message": "Capturing desktop screenshot…"})

        feed = LiveScreenFeed(mask_overlay=False)
        vision = feed.capture_oneshot()
        if vision is None or not vision.frame_b64:
            reply = "I couldn't capture the screen right now. Try again in a moment."
            return SkillResult(reply=reply, skill_id="observe")

        ctx.emit("observation", {
            "native_size": vision.native_size,
            "image_size": vision.image_size,
        })
        ctx.emit("activity", {
            "step": "describe",
            "message": f"Describing screen ({vision.native_size[0]}×{vision.native_size[1]})…",
        })

        reply = describe_screen(
            ctx.message,
            frame_b64=vision.frame_b64,
            on_token=lambda t: ctx.emit("skill_token", {"text": t}),
            voice_mode=ctx.voice_mode,
        )
        if not reply.strip():
            reply = "I captured the screen but couldn't describe it. Please try again."
        return SkillResult(
            reply=reply.strip(),
            skill_id="observe",
            metadata={"native_size": vision.native_size},
        )
