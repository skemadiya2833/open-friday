"""Wav2Lip optional low-VRAM engine under data/vendor/Wav2Lip."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from friday.avatar.base import AvatarResult


def _vendor_root() -> Path:
    from friday.config import DATA_DIR

    return Path(DATA_DIR) / "vendor" / "Wav2Lip"


def _wav2lip_python() -> str:
    """Prefer the vendor venv so Friday's env stays free of Wav2Lip torch pins."""
    import os

    override = (os.getenv("FRIDAY_WAV2LIP_PYTHON") or "").strip()
    if override and Path(override).is_file():
        return override
    root = _vendor_root()
    for cand in (
        root / ".venv" / "Scripts" / "python.exe",
        root / ".venv" / "bin" / "python",
    ):
        if cand.is_file():
            return str(cand)
    return shutil.which("python") or sys.executable


class Wav2LipEngine:
    name = "wav2lip"

    def available(self) -> bool:
        root = _vendor_root()
        if not (root / "inference.py").is_file():
            return False
        ckpt = root / "checkpoints" / "wav2lip_gan.pth"
        if not ckpt.is_file():
            ckpt = root / "checkpoints" / "wav2lip.pth"
        return ckpt.is_file()

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
                mode="wav2lip",
                message="Wav2Lip not installed under data/vendor/Wav2Lip — using still.",
            )
        if not portrait.is_file():
            return AvatarResult(
                ok=False, mode="wav2lip", message="No portrait for this skin."
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
        checkpoint = root / "checkpoints" / "wav2lip_gan.pth"
        if not checkpoint.is_file():
            checkpoint = root / "checkpoints" / "wav2lip.pth"
        py = _wav2lip_python()
        cmd = [
            py,
            str(root / "inference.py"),
            "--checkpoint_path",
            str(checkpoint),
            "--face",
            str(portrait),
            "--audio",
            str(audio_path),
            "--outfile",
            str(out_mp4),
        ]
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
        except Exception as exc:  # noqa: BLE001
            return AvatarResult(
                ok=False,
                mode="wav2lip",
                portrait_path=str(portrait.resolve()),
                message=f"Wav2Lip failed ({exc}); still portrait.",
            )
        if out_mp4.is_file():
            return AvatarResult(
                ok=True,
                mode="wav2lip",
                portrait_path=str(portrait.resolve()),
                video_path=str(out_mp4.resolve()),
                message="Wav2Lip lip-sync ready.",
            )
        err = (proc.stderr or proc.stdout or "")[:200]
        return AvatarResult(
            ok=False,
            mode="wav2lip",
            portrait_path=str(portrait.resolve()),
            message=f"Wav2Lip produced no video ({err or 'unknown'}); still portrait.",
        )
