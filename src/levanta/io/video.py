"""Frame extraction from a phone video.

Feed-forward reconstruction wants a few dozen *sharp*, *well spread* frames rather than
every frame of the clip.  We divide the timeline into windows of ``1 / fps`` seconds and
keep the sharpest frame of each window (variance of the Laplacian), which throws away
motion-blurred frames without leaving holes in the coverage.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass
class ExtractedFrame:
    path: Path
    index: int
    time_s: float
    sharpness: float


def _sharpness(gray: np.ndarray) -> float:
    import cv2

    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def extract_frames(
    video_path: str | Path,
    out_dir: str | Path,
    fps: float = 2.0,
    max_frames: int | None = None,
    max_side: int | None = 1024,
    min_sharpness: float = 20.0,
    jpeg_quality: int = 95,
) -> list[ExtractedFrame]:
    """Write the sharpest frame of every ``1/fps`` window of ``video_path`` to ``out_dir``.

    Returns the frames in time order.  Frames whose sharpness is below ``min_sharpness``
    are dropped even if they were the best of their window.
    """
    import cv2

    video_path = Path(video_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise FileNotFoundError(f"cannot open video {video_path}")
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    window = max(1, round(src_fps / fps))

    kept: list[ExtractedFrame] = []
    best: tuple[float, np.ndarray, int] | None = None
    i = 0
    while True:
        ok, bgr = cap.read()
        if not ok:
            break
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        if gray.shape[1] > 640:
            scale = 640 / gray.shape[1]
            gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        s = _sharpness(gray)
        if best is None or s > best[0]:
            best = (s, bgr, i)
        if (i + 1) % window == 0:
            if best is not None and best[0] >= min_sharpness:
                kept.append(_save(best, out_dir, src_fps, max_side, jpeg_quality, len(kept)))
                if max_frames is not None and len(kept) >= max_frames:
                    break
            best = None
        i += 1
    if best is not None and best[0] >= min_sharpness and (max_frames is None or len(kept) < max_frames):
        kept.append(_save(best, out_dir, src_fps, max_side, jpeg_quality, len(kept)))
    cap.release()
    return kept


def _save(
    best: tuple[float, np.ndarray, int], out_dir: Path, src_fps: float, max_side: int | None, q: int, n: int
) -> ExtractedFrame:
    import cv2

    s, bgr, idx = best
    if max_side is not None and max(bgr.shape[:2]) > max_side:
        scale = max_side / max(bgr.shape[:2])
        bgr = cv2.resize(bgr, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    path = out_dir / f"frame_{n:05d}.jpg"
    cv2.imwrite(str(path), bgr, [int(cv2.IMWRITE_JPEG_QUALITY), q])
    return ExtractedFrame(path=path, index=idx, time_s=idx / src_fps, sharpness=s)
