"""Still portrait while TTS plays — always available fallback."""

from __future__ import annotations

from pathlib import Path

from friday.avatar.base import AvatarResult


class StillEngine:
    name = "still"

    def available(self) -> bool:
        return True

    def render(
        self,
        *,
        portrait: Path,
        audio_path: Path | None,
        out_dir: Path,
    ) -> AvatarResult:
        if not portrait.is_file():
            return AvatarResult(
                ok=False, mode="still", message="No portrait uploaded for this skin."
            )
        return AvatarResult(
            ok=True,
            mode="still",
            portrait_path=str(portrait.resolve()),
            message="Showing still portrait while speech plays.",
        )
