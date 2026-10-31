"""Per-callsign talking-head video — loop/fit to TTS instead of generating Wav2Lip."""

from __future__ import annotations

from pathlib import Path


def talking_dir() -> Path:
    from friday.config import DATA_DIR

    p = Path(DATA_DIR) / "presence" / "talking"
    p.mkdir(parents=True, exist_ok=True)
    return p


def talking_video_path(skin_id: str) -> Path:
    sid = (skin_id or "").strip().lower()
    return talking_dir() / f"{sid}.mp4"


def has_talking_video(skin_id: str) -> bool:
    p = talking_video_path(skin_id)
    return p.is_file() and p.stat().st_size > 1000


def talking_video_url(skin_id: str) -> str | None:
    p = talking_video_path(skin_id)
    if not (p.is_file() and p.stat().st_size > 1000):
        return None
    return f"/api/presence/talking/{skin_id.strip().lower()}?t={int(p.stat().st_mtime)}"


def mouth_atlas_url(skin_id: str) -> str | None:
    p = talking_video_path(skin_id)
    from friday.presence.mouth_atlas import mouth_atlas_path

    atlas = mouth_atlas_path(p)
    if not atlas.is_file():
        return None
    return f"/api/presence/talking/{skin_id.strip().lower()}/mouth?t={int(atlas.stat().st_mtime)}"


def install_talking_video(skin_id: str, src: Path) -> Path:
    """Copy/convert a source clip into the canonical talking mp4 for a skin."""
    import shutil
    import subprocess

    sid = skin_id.strip().lower()
    dest = talking_video_path(sid)
    dest.parent.mkdir(parents=True, exist_ok=True)
    src = Path(src)
    if not src.is_file():
        raise FileNotFoundError(str(src))
    # Prefer ffmpeg re-mux to H.264 + AAC for browser playback; fall back to copy.
    try:
        proc = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(src),
                "-an",  # TTS carries audio; keep clip silent to avoid double-speak
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(dest),
            ],
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        if proc.returncode != 0 or not dest.is_file() or dest.stat().st_size < 1000:
            raise RuntimeError(proc.stderr[-400:] if proc.stderr else "ffmpeg failed")
    except Exception:
        shutil.copy2(src, dest)
    # Cut the clip into mouth-shape pools for HUD phonetic-ish seeking.
    try:
        from friday.presence.mouth_atlas import write_mouth_atlas

        write_mouth_atlas(dest)
    except Exception:
        pass
    return dest


def extract_portrait_from_video(video: Path, dest: Path) -> Path:
    """Grab a mid frame as the still portrait."""
    import subprocess

    dest.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-ss",
            "0.4",
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(dest),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if proc.returncode != 0 or not dest.is_file():
        raise RuntimeError(proc.stderr[-300:] if proc.stderr else "frame extract failed")
    return dest
