"""Prep a head-and-shoulders still for Wav2Lip (wav2lip.org medium-style).

The site's good clips are ~624px head+shoulders with lips on the mouth.
Vanilla Wav2Lip only rewrites the lower half of the face box and hard-pastes
it back — on a torso shot that becomes "lips on the shirt", and a tight
480 crop that then gets ``resize_factor=2`` becomes a blurry 240px mess.

We detect the face, build a medium pose crop (face + a bit of shoulders),
scale to ~624px, and leave blending to ``inference.py``'s feathered paste.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def _pose_scale() -> float:
    # medium ≈ site "medium pose" — face + neck/shoulders, not shirt-only.
    raw = (os.getenv("FRIDAY_WAV2LIP_POSE_SCALE") or "medium").strip().lower()
    named = {"small": 1.35, "medium": 1.65, "large": 2.0}
    if raw in named:
        return named[raw]
    try:
        return max(1.15, min(2.4, float(raw)))
    except ValueError:
        return 1.65


def _max_side() -> int:
    # Match the user's wav2lip.org export (624×624).
    try:
        return max(320, min(768, int(os.getenv("FRIDAY_WAV2LIP_MAX_SIDE") or "624")))
    except ValueError:
        return 624


def _lip_pads() -> list[int]:
    raw = (os.getenv("FRIDAY_WAV2LIP_PADS") or "").strip()
    if raw:
        parts = [int(x) for x in raw.replace(",", " ").split() if x.strip()]
        if len(parts) == 4:
            return parts
    level = (os.getenv("FRIDAY_WAV2LIP_LIP_SCALE") or "medium").strip().lower()
    if level == "small":
        return [0, 10, 0, 0]
    if level == "large":
        return [0, 25, 6, 6]
    # medium — chin included, not the whole torso
    return [0, 18, 4, 4]


def _largest_haar(gray) -> tuple[int, int, int, int] | None:
    import cv2

    cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )
    if cascade.empty():
        return None
    faces = cascade.detectMultiScale(
        gray, scaleFactor=1.08, minNeighbors=5, minSize=(64, 64)
    )
    if faces is None or len(faces) == 0:
        return None
    h = gray.shape[0]
    ranked = sorted(faces, key=lambda f: f[2] * f[3], reverse=True)
    for x, y, fw, fh in ranked:
        if (y + fh / 2) <= h * 0.72:
            return int(x), int(y), int(fw), int(fh)
    x, y, fw, fh = ranked[0]
    return int(x), int(y), int(fw), int(fh)


def _s3fd_box(img, vendor_root: Path) -> tuple[int, int, int, int] | None:
    import sys

    import numpy as np

    root = str(vendor_root)
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        import face_detection
        import torch
    except Exception:  # noqa: BLE001
        return None
    device = "cuda" if torch.cuda.is_available() else "cpu"
    try:
        det = face_detection.FaceAlignment(
            face_detection.LandmarksType._2D, flip_input=False, device=device
        )
        preds = det.get_detections_for_batch(np.array([img]))
    except Exception:  # noqa: BLE001
        return None
    if not preds or preds[0] is None:
        return None
    x1, y1, x2, y2 = preds[0]
    return int(x1), int(y1), int(x2 - x1), int(y2 - y1)


def prepare_face_still(
    portrait: Path,
    dest: Path,
    *,
    vendor_root: Path | None = None,
) -> dict[str, Any]:
    """Write a ~624px head-and-shoulders still. Returns crop meta + pads."""
    import cv2

    img = cv2.imread(str(portrait), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"Could not read portrait: {portrait}")
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    detector = "fallback"
    box = _largest_haar(gray)
    if box is not None:
        detector = "haar"
    elif vendor_root is not None:
        box = _s3fd_box(img, vendor_root)
        if box is not None:
            detector = "s3fd"

    if box is None:
        side = int(min(h, w) * 0.62)
        cx, cy = w // 2, int(h * 0.40)
        x = max(0, cx - side // 2)
        y = max(0, cy - side // 2)
        box = (x, y, side, side)

    x, y, fw, fh = box
    # Keep a face-like aspect from the *top* of the detector box so the shirt
    # is not inside the region Wav2Lip rewrites (lower half of the box).
    if fh > int(fw * 1.15):
        fh = int(fw * 1.10)

    scale = _pose_scale()
    side = int(max(fw, fh) * scale)
    cx = x + fw / 2.0
    # Center a bit below the face mid so shoulders enter the frame like the site.
    cy = y + fh * 0.55
    x1 = int(round(cx - side / 2))
    y1 = int(round(cy - side / 2))
    x2 = x1 + side
    y2 = y1 + side

    if x1 < 0:
        x2 -= x1
        x1 = 0
    if y1 < 0:
        y2 -= y1
        y1 = 0
    if x2 > w:
        x1 = max(0, x1 - (x2 - w))
        x2 = w
    if y2 > h:
        y1 = max(0, y1 - (y2 - h))
        y2 = h

    crop = img[y1:y2, x1:x2].copy()
    max_side = _max_side()
    ch, cw = crop.shape[:2]
    long = max(ch, cw)
    if long != max_side and long > 0:
        scale_img = max_side / float(long)
        crop = cv2.resize(
            crop,
            (max(2, int(cw * scale_img)), max(2, int(ch * scale_img))),
            interpolation=cv2.INTER_AREA if scale_img < 1 else cv2.INTER_CUBIC,
        )
    ch, cw = crop.shape[:2]
    crop = crop[: ch - (ch % 2), : cw - (cw % 2)]

    dest.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(dest), crop):
        raise ValueError(f"Failed to write face still: {dest}")

    return {
        "ok": True,
        "path": str(dest),
        "src_box": [x1, y1, x2, y2],
        "out_size": [int(crop.shape[1]), int(crop.shape[0])],
        "pose_scale": scale,
        "max_side": max_side,
        "pads": _lip_pads(),
        "detector": detector,
    }
