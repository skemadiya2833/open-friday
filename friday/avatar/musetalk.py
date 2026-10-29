"""MuseTalk lip-sync engine — optional CUDA vendor install under data/vendor/MuseTalk."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from friday.avatar.base import AvatarResult


def _vendor_root() -> Path:
    from friday.config import DATA_DIR

    return Path(DATA_DIR) / "vendor" / "MuseTalk"


class MuseTalkEngine:
    name = "musetalk"

    def available(self) -> bool:
        root = _vendor_root()
        if not root.is_dir():
            return False
        # Inference entrypoints vary by MuseTalk version — any of these counts as installed.
        markers = (
            root / "scripts" / "inference.py",
            root / "infer.py",
            root / "app.py",
        )
        return any(p.is_file() for p in markers)

    def render(
        self,
        *,
        portrait: Path,
        audio_path: Path | None,
        out_dir: Path,
    ) -> AvatarResult:
        if not self.available():
            return AvatarResult(
                ok=False,
                mode="musetalk",
                message="MuseTalk not installed under data/vendor/MuseTalk — using still portrait.",
            )
        if not portrait.is_file():
            return AvatarResult(
                ok=False, mode="musetalk", message="No portrait for this skin."
            )
        if audio_path is None or not Path(audio_path).is_file():
            return AvatarResult(
                ok=True,
                mode="still",
                portrait_path=str(portrait.resolve()),
                message="No audio yet — still portrait.",
            )
        out_dir.mkdir(parents=True, exist_ok=True)
        out_mp4 = out_dir / "lipsync.mp4"
        root = _vendor_root()
        script = next(
            (
                p
                for p in (
                    root / "scripts" / "inference.py",
                    root / "infer.py",
                )
                if p.is_file()
            ),
            None,
        )
        if script is None:
            return AvatarResult(
                ok=False,
                mode="musetalk",
                portrait_path=str(portrait.resolve()),
                message="MuseTalk folder present but no inference script found.",
            )
        py = shutil.which("python") or sys.executable
        try:
            # Best-effort CLI; vendor scripts differ — failure falls back to still.
            proc = subprocess.run(
                [
                    py,
                    str(script),
                    "--audio",
                    str(audio_path),
                    "--source",
                    str(portrait),
                    "--result_dir",
                    str(out_dir),
                ],
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
        except Exception as exc:  # noqa: BLE001
            return AvatarResult(
                ok=False,
                mode="musetalk",
                portrait_path=str(portrait.resolve()),
                message=f"MuseTalk failed ({exc}); still portrait.",
            )
        if out_mp4.is_file() or list(out_dir.glob("*.mp4")):
            video = out_mp4 if out_mp4.is_file() else next(out_dir.glob("*.mp4"))
            return AvatarResult(
                ok=True,
                mode="musetalk",
                portrait_path=str(portrait.resolve()),
                video_path=str(video.resolve()),
                message="MuseTalk lip-sync ready.",
            )
        err = (proc.stderr or proc.stdout or "")[:200]
        return AvatarResult(
            ok=False,
            mode="musetalk",
            portrait_path=str(portrait.resolve()),
            message=f"MuseTalk produced no video ({err or 'unknown'}); still portrait.",
        )
