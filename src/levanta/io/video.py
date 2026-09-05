"""Frame extraction from a phone video.

Feed-forward reconstruction wants a few dozen *sharp*, *well spread* frames rather than
every frame of the clip.  We divide the timeline into windows of ``1 / fps`` seconds and
keep the sharpest frame of each window (variance of the Laplacian), which throws away
motion-blurred frames without leaving holes in the coverage.  When the network can only
take ``max_frames`` views, they are spread over the *whole* clip (the sharpest window of
each of ``max_frames`` equal stretches of time), never just the first seconds.
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


FLAT_MAX = 0.6  # measured: title cards 0.87-0.98, rooms 0.07-0.31


def _flatness(gray: np.ndarray) -> float:
    """Fraction of pixels inside the dominant band of 9 grey levels.

    A title card (text on black), a fade, a lens cap or a plain wall filling the frame
    score above ``FLAT_MAX``; text on black is also the sharpest thing in a clip by
    variance of the Laplacian, which is why sharpness alone picked six title cards out of
    24 frames on the first real walkthrough.
    """
    h = np.bincount(gray.ravel(), minlength=256).astype(float)
    return float(np.convolve(h, np.ones(9), "same").max() / gray.size)


def _usable(gray: np.ndarray) -> float:
    """Sharpness of a frame worth keeping, 0 for a flat one."""
    return 0.0 if _flatness(gray) > FLAT_MAX else _sharpness(gray)


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
    are dropped even if they were the best of their window, and so are flat frames (title
    cards, fades, a wall filling the picture).  With ``max_frames`` the clip
    is cut into that many equal stretches and the sharpest window of each is kept, so a
    long walk is covered end to end; stretches that are all blur are filled with the
    sharpest leftover windows.
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

    candidates: list[tuple[float, bytes, int]] = []  # (sharpness, encoded jpeg, frame index)
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
        s = _usable(gray)
        if best is None or s > best[0]:
            best = (s, bgr, i)
        if (i + 1) % window == 0:
            if best is not None and best[0] >= min_sharpness:
                candidates.append(_encode(best, max_side, jpeg_quality))
            best = None
        i += 1
    if best is not None and best[0] >= min_sharpness:
        candidates.append(_encode(best, max_side, jpeg_quality))
    cap.release()

    chosen = _spread(candidates, max_frames, i)
    return [_write(c, out_dir, src_fps, n) for n, c in enumerate(chosen)]


def _spread(candidates: list[tuple[float, bytes, int]], max_frames: int | None, n_total: int) -> list[tuple[float, bytes, int]]:
    """Keep ``max_frames`` candidates spread over the clip: the sharpest of each equal
    stretch of frame indices, then the sharpest leftovers for stretches that were all blur."""
    if max_frames is None or len(candidates) <= max_frames:
        return candidates
    n_total = max(n_total, 1)
    per_bin: dict[int, tuple[float, bytes, int]] = {}
    for c in candidates:
        b = min(max_frames - 1, int(c[2] * max_frames / n_total))
        if b not in per_bin or c[0] > per_bin[b][0]:
            per_bin[b] = c
    chosen = list(per_bin.values())
    if len(chosen) < max_frames:
        taken = {id(c) for c in chosen}
        for c in sorted(candidates, key=lambda c: -c[0]):
            if len(chosen) >= max_frames:
                break
            if id(c) not in taken:
                chosen.append(c)
                taken.add(id(c))
    return sorted(chosen, key=lambda c: c[2])


def inspect_video(video_path: str | Path, fps: float = 1.0, min_sharpness: float = 20.0, max_probe: int = 600) -> dict:
    """Quick quality report without writing anything: size, length, sharpness, usable frames.

    Up to ``max_probe`` frames spread over the clip are scored; the estimate of usable
    frames assumes one frame per ``1/fps`` window.
    """
    import cv2

    video_path = Path(video_path)
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise FileNotFoundError(f"cannot open video {video_path}")
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    duration = n / src_fps if src_fps else 0.0
    step = max(1, n // max_probe) if n else 1
    window = max(1, round(src_fps / fps))
    probes: list[tuple[int, float, bool]] = []  # (frame index, sharpness, flat)
    idx = 0
    while True:
        ok = cap.grab()
        if not ok:
            break
        if idx % step == 0:
            ok, bgr = cap.retrieve()
            if ok:
                gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
                if gray.shape[1] > 640:
                    s = 640 / gray.shape[1]
                    gray = cv2.resize(gray, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
                is_flat = _flatness(gray) > FLAT_MAX
                probes.append((idx, 0.0 if is_flat else _sharpness(gray), is_flat))
        idx += 1
    cap.release()
    # judge every real 1/fps window by the probes that fell in it
    wins: dict[int, list[tuple[float, bool]]] = {}
    for i, sc, fl in probes:
        wins.setdefault(i // window, []).append((sc, fl))
    flat_windows = sum(1 for v in wins.values() if all(fl for _, fl in v))
    usable = sum(1 for v in wins.values() if max(sc for sc, _ in v) >= min_sharpness)
    blurry_windows = len(wins) - usable - flat_windows
    room_scores = np.asarray([sc for _, sc, fl in probes if not fl]) if any(not fl for _, _, fl in probes) else np.zeros(1)
    warnings: list[str] = []
    if duration < 20:
        warnings.append("shorter than 20 s: walk slowly through every room, 30-60 s per room")
    if min(w, h) < 700:
        warnings.append(f"low resolution ({w}x{h}): 1080p gives noticeably better walls")
    if np.median(room_scores) < 40:
        warnings.append("mostly blurry: move slower, more light, no zoom")
    if flat_windows:
        warnings.append(f"{flat_windows / fps:.0f} s of title cards or blank frames: skipped (they are not the house)")
    if usable < 12:
        warnings.append(f"only ~{usable} usable frames at {fps:g} fps: film longer or raise --fps")
    return {
        "width": w,
        "height": h,
        "fps": float(src_fps),
        "frames": n,
        "duration_s": float(duration),
        "sharpness_median": float(np.median(room_scores)),
        "sharpness_p10": float(np.percentile(room_scores, 10)),
        "usable_frames": int(usable),
        "blurry_windows": int(blurry_windows),
        "flat_windows": int(flat_windows),
        "warnings": warnings,
    }


def _encode(best: tuple[float, np.ndarray, int], max_side: int | None, q: int) -> tuple[float, bytes, int]:
    import cv2

    s, bgr, idx = best
    if max_side is not None and max(bgr.shape[:2]) > max_side:
        scale = max_side / max(bgr.shape[:2])
        bgr = cv2.resize(bgr, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), q])
    if not ok:
        raise RuntimeError("could not encode a frame as JPEG")
    return s, buf.tobytes(), idx


def _write(cand: tuple[float, bytes, int], out_dir: Path, src_fps: float, n: int) -> ExtractedFrame:
    s, data, idx = cand
    path = out_dir / f"frame_{n:05d}.jpg"
    path.write_bytes(data)
    return ExtractedFrame(path=path, index=idx, time_s=idx / src_fps, sharpness=s)
