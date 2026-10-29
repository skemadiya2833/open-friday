"""Avatar engine protocol — still portrait or lip-sync clip for HUD."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass
class AvatarResult:
    ok: bool
    mode: str  # still | musetalk | wav2lip | none
    portrait_path: str | None = None
    video_path: str | None = None
    message: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "mode": self.mode,
            "portrait_path": self.portrait_path,
            "video_path": self.video_path,
            "message": self.message,
        }


class AvatarEngine(Protocol):
    name: str

    def available(self) -> bool: ...

    def render(
        self,
        *,
        portrait: Path,
        audio_path: Path | None,
        out_dir: Path,
    ) -> AvatarResult: ...
