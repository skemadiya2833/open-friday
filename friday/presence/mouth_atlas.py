"""Build a mouth-openness atlas from a talking-head clip for HUD segment seeking."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any


CLASSES = ("rest", "closed", "narrow", "mid", "wide")


def mouth_atlas_path(video_path: Path) -> Path:
    return Path(video_path).with_suffix(".mouth.json")


def _label(v: float) -> str:
    if v < 0.18:
        return "rest"
    if v < 0.38:
        return "closed"
    if v < 0.58:
        return "narrow"
    if v < 0.78:
        return "mid"
    return "wide"


def analyze_mouth_curve(video_path: Path) -> tuple[float, list[float]]:
    """Return (fps, per-frame openness 0..1) using lower-face dark cavity + edges."""
    import cv2
    import numpy as np

    path = Path(video_path)
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open talking video: {path}")
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 25.0) or 25.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    scores: list[float] = []
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if w <= 0 or h <= 0:
                h, w = frame.shape[:2]
            # Head-and-shoulders portraits put lips higher than a full-body crop.
            y0, y1 = int(h * 0.48), int(h * 0.66)
            x0, x1 = int(w * 0.34), int(w * 0.66)
            roi = frame[y0:y1, x0:x1]
            if roi.size == 0:
                scores.append(0.0)
                continue
            gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
            # Illustrated open mouth: bright teeth and/or a darker inner gap.
            teeth = float(((hsv[:, :, 2] > 175) & (hsv[:, :, 1] < 70)).mean())
            dark = float((gray < 70).mean())
            edges = cv2.Canny(gray, 40, 120)
            edge = float((edges > 0).mean())
            # Vertical aperture: mid-band vs lip bands.
            mid = gray[gray.shape[0] // 3 : 2 * gray.shape[0] // 3]
            gap = float(np.std(mid) / 48.0) if mid.size else 0.0
            contrast = float(np.std(gray) / 64.0)
            scores.append(
                0.40 * min(1.0, teeth * 10.0)
                + 0.25 * min(1.0, dark * 4.0)
                + 0.20 * min(1.0, gap)
                + 0.10 * min(1.0, edge * 3.0)
                + 0.05 * min(1.0, contrast)
            )
    finally:
        cap.release()
    if not scores:
        raise RuntimeError("empty talking video")
    arr = np.asarray(scores, dtype=np.float64)
    k = 5
    sm = np.convolve(arr, np.ones(k) / k, mode="same")
    lo, hi = float(np.percentile(sm, 8)), float(np.percentile(sm, 92))
    norm = np.clip((sm - lo) / max(1e-6, hi - lo), 0.0, 1.0)
    return fps, [float(x) for x in norm]


def build_mouth_atlas(video_path: Path) -> dict[str, Any]:
    """Segment the clip into rest/closed/narrow/mid/wide mouth pools."""
    import numpy as np

    path = Path(video_path)
    fps, curve = analyze_mouth_curve(path)
    labels = [_label(v) for v in curve]
    raw: list[dict[str, Any]] = []
    i = 0
    while i < len(labels):
        j = i + 1
        while j < len(labels) and labels[j] == labels[i]:
            j += 1
        raw.append({"cls": labels[i], "f0": i, "f1": j - 1})
        i = j
    merged: list[dict[str, Any]] = []
    for s in raw:
        dur = s["f1"] - s["f0"] + 1
        if merged and dur < 4:
            merged[-1]["f1"] = s["f1"]
            continue
        merged.append(dict(s))

    pools: dict[str, list[dict[str, float]]] = defaultdict(list)
    timeline: list[dict[str, Any]] = []
    for s in merged:
        f0, f1 = int(s["f0"]), int(s["f1"])
        mean = float(np.mean(curve[f0 : f1 + 1]))
        cls = _label(mean)
        t0 = round(f0 / fps, 3)
        t1 = round((f1 + 1) / fps, 3)
        if t1 - t0 < 0.12:
            continue
        item = {"t0": t0, "t1": t1, "open": round(mean, 3)}
        pools[cls].append(item)
        timeline.append({"cls": cls, **item})

    atlas: dict[str, Any] = {
        "version": 1,
        "fps": fps,
        "duration": round(len(curve) / fps, 3),
        "pools": {k: pools[k] for k in CLASSES if pools.get(k)},
        "timeline": timeline,
    }
    return atlas


def write_mouth_atlas(video_path: Path) -> Path:
    path = Path(video_path)
    atlas = build_mouth_atlas(path)
    dest = mouth_atlas_path(path)
    dest.write_text(json.dumps(atlas, indent=2), encoding="utf-8")
    return dest


def load_mouth_atlas(video_path: Path) -> dict[str, Any] | None:
    dest = mouth_atlas_path(video_path)
    if not dest.is_file():
        return None
    try:
        return json.loads(dest.read_text(encoding="utf-8"))
    except Exception:
        return None
