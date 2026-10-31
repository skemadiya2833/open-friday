"""Wav2Lip optional lip-sync engine under data/vendor/Wav2Lip."""

from __future__ import annotations

import os
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


def _yield_env_on() -> bool:
    return (os.getenv("FRIDAY_WAV2LIP_YIELD_GPU") or "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _yield_ollama_for_wav2lip() -> str | None:
    """Temporarily unload the hot chat tag so Wav2Lip can use dedicated VRAM.

    Ollama with ``keep_alive=-1`` pins several GB; Wav2Lip then spills into
    Windows *shared* GPU memory (system RAM) even when Task Manager shows free
    dedicated VRAM. Set ``FRIDAY_WAV2LIP_YIELD_GPU=0`` to skip.
    """
    if not _yield_env_on():
        return None
    try:
        import httpx

        from friday.config import OLLAMA_HOST, resolve_chat_model

        tag = resolve_chat_model()
        httpx.post(
            f"{OLLAMA_HOST.rstrip('/')}/api/generate",
            json={"model": tag, "prompt": "", "keep_alive": 0},
            timeout=45.0,
        )
        print(f"[Wav2Lip] yielded GPU — unloaded {tag} for lip-sync", flush=True)
        return tag
    except Exception as exc:  # noqa: BLE001
        print(f"[Wav2Lip] yield GPU skipped: {exc}", flush=True)
        return None


def _rewarm_ollama(tag: str | None) -> None:
    if not tag:
        return
    try:
        import httpx

        from friday.config import OLLAMA_HOST
        from friday.runtime.resource_policy import keep_alive_for_role

        httpx.post(
            f"{OLLAMA_HOST.rstrip('/')}/api/generate",
            json={
                "model": tag,
                "prompt": "",
                "keep_alive": keep_alive_for_role("main"),
            },
            timeout=120.0,
        )
        print(f"[Wav2Lip] re-warmed {tag}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[Wav2Lip] re-warm skipped: {exc}", flush=True)


def _release_wav2lip_cuda(py: str) -> None:
    """Drop leftover CUDA caches in the Wav2Lip venv after inference."""
    try:
        subprocess.run(
            [
                py,
                "-c",
                "import torch\n"
                "if torch.cuda.is_available():\n"
                "  torch.cuda.empty_cache()\n"
                "  torch.cuda.ipc_collect()\n",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except Exception:  # noqa: BLE001
        pass


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
        # Drop stale clip so success is unambiguous.
        try:
            out_mp4.unlink(missing_ok=True)
        except OSError:
            pass
        root = _vendor_root()
        checkpoint = root / "checkpoints" / "wav2lip_gan.pth"
        if not checkpoint.is_file():
            checkpoint = root / "checkpoints" / "wav2lip.pth"
        py = _wav2lip_python()

        # Site-style prep: detect face → medium pose (head+shoulders) → ~624px.
        # Never apply resize_factor after this — that was producing blurry 240p trash.
        face_still = out_dir / "face_still.png"
        try:
            from friday.avatar.wav2lip_face import _lip_pads, prepare_face_still

            meta = prepare_face_still(
                Path(portrait), face_still, vendor_root=root
            )
            pads = meta.get("pads") or _lip_pads()
            print(
                f"[Wav2Lip] face prep {meta.get('out_size')} pose={meta.get('pose_scale')} "
                f"det={meta.get('detector')} pads={pads}",
                flush=True,
            )
            face_path = face_still
            resize_factor = "1"
        except Exception as exc:  # noqa: BLE001
            print(f"[Wav2Lip] face prep failed ({exc}) — using full portrait", flush=True)
            face_path = Path(portrait)
            pads = [0, 18, 4, 4]
            # Full 1254px portrait: downscale once so the 96px model isn't upscaled hard.
            resize_factor = os.getenv("FRIDAY_WAV2LIP_RESIZE", "2")

        cmd = [
            py,
            str(root / "inference.py"),
            "--checkpoint_path",
            str(checkpoint.resolve()),
            "--face",
            str(face_path.resolve()),
            "--audio",
            str(Path(audio_path).resolve()),
            "--outfile",
            str(out_mp4.resolve()),
            "--resize_factor",
            resize_factor,
            "--wav2lip_batch_size",
            os.getenv("FRIDAY_WAV2LIP_BATCH", "16"),
            "--face_det_batch_size",
            os.getenv("FRIDAY_WAV2LIP_FACE_BATCH", "2"),
            "--pads",
            str(pads[0]),
            str(pads[1]),
            str(pads[2]),
            str(pads[3]),
            "--nosmooth",
        ]
        env = os.environ.copy()
        env.setdefault("CUDA_DEVICE_ORDER", "PCI_BUS_ID")
        # Prefer dedicated VRAM; shrink fragmentation after Ollama residency.
        env.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
        rewarm_tag = _yield_ollama_for_wav2lip()
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=240,
                check=False,
                env=env,
            )
        except Exception as exc:  # noqa: BLE001
            _rewarm_ollama(rewarm_tag)
            return AvatarResult(
                ok=False,
                mode="wav2lip",
                portrait_path=str(portrait.resolve()),
                message=f"Wav2Lip failed ({exc}); still portrait.",
            )
        _release_wav2lip_cuda(py)
        _rewarm_ollama(rewarm_tag)
        if out_mp4.is_file() and out_mp4.stat().st_size > 1000:
            return AvatarResult(
                ok=True,
                mode="wav2lip",
                portrait_path=str(portrait.resolve()),
                video_path=str(out_mp4.resolve()),
                message="Wav2Lip lip-sync ready.",
            )
        err = ((proc.stderr or "") + "\n" + (proc.stdout or "")).strip()
        # Prefer the last useful line.
        tail = "\n".join(err.splitlines()[-8:])[:400]
        print(f"[Wav2Lip] no video — {tail}", flush=True)
        return AvatarResult(
            ok=False,
            mode="wav2lip",
            portrait_path=str(portrait.resolve()),
            message=f"Wav2Lip produced no video ({tail or 'unknown'}); still portrait.",
        )
