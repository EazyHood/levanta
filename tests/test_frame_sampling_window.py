"""Scoring one frame in three must never skip whole windows.

`score_every=3` (round 3, a 2.6x speed-up on a 30 fps clip) assumes a window of ~30
frames.  On the Replica walk — a 1 fps video asked for at `--fps 1`, so one frame per
window — it scored frames 0, 3, 6 ... and 85 of 116 frames were never candidates: the
network saw 31 views of an apartment instead of 94.

Thresholds written before the fix ran:
- a 1 fps clip at --fps 1 keeps every sharp frame (the blurry ones still go);
- a 30 fps clip at --fps 1 still skips two frames in three (the speed-up survives);
- at any fps, every window that has a sharp frame contributes one.
"""

from __future__ import annotations

import numpy as np
import pytest

from levanta.io.video import extract_frames


def _clip(path, n_frames, fps, sharp_every=1):
    cv2 = pytest.importorskip("cv2")
    w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (160, 120))
    rng = np.random.default_rng(2)
    for i in range(n_frames):
        if i % sharp_every == 0:
            frame = rng.integers(0, 255, (120, 160, 3), dtype=np.uint8)
        else:
            frame = np.full((120, 160, 3), 128, np.uint8)  # flat grey: blurry and skippable
        w.write(frame)
    w.release()
    return path


def test_one_frame_per_second_clip_keeps_them_all(tmp_path):
    clip = _clip(tmp_path / "walk.mp4", 60, 1.0)
    kept = extract_frames(clip, tmp_path / "f", fps=1.0, min_sharpness=20.0)
    assert len(kept) == 60, len(kept)
    assert [k.index for k in kept] == list(range(60))


def test_a_thirty_fps_clip_still_scores_one_frame_in_three(tmp_path, monkeypatch):
    import levanta.io.video as video

    seen: list[int] = []
    real = video._sharpness
    monkeypatch.setattr(video, "_sharpness", lambda g: (seen.append(1), real(g))[1])
    clip = _clip(tmp_path / "fast.mp4", 300, 30.0)
    kept = extract_frames(clip, tmp_path / "f", fps=1.0, min_sharpness=20.0)
    assert 9 <= len(kept) <= 10  # one per second
    assert 90 <= len(seen) <= 110  # a third of 300, not all of them


def test_every_window_with_a_sharp_frame_contributes_one(tmp_path):
    # 4 fps clip asked for at 2 fps: windows of 2 frames, only the even ones sharp
    clip = _clip(tmp_path / "half.mp4", 40, 4.0, sharp_every=2)
    kept = extract_frames(clip, tmp_path / "f", fps=2.0, min_sharpness=20.0)
    assert len(kept) == 20, len(kept)
    assert all(k.index % 2 == 0 for k in kept)
