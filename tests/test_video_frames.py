"""Frames given to the network must cover the whole walk, not its first seconds.

Regression for the first real phone walkthrough (220 s, CC BY): ``--max-views 24`` at 1 fps
kept the first 24 sharp seconds and the reconstruction stopped at the entrance hall.

Thresholds written before the fix ran:
- the kept frames span at least 80 % of the clip;
- the largest gap between consecutive kept frames is at most 2.5x the median gap;
- blurry stretches are still skipped and the frames come back in time order.
"""

from __future__ import annotations

import numpy as np
import pytest

SPAN_MIN = 0.80
GAP_RATIO_MAX = 2.5


@pytest.fixture(scope="module")
def long_clip(tmp_path_factory):
    cv2 = pytest.importorskip("cv2")
    p = tmp_path_factory.mktemp("clip") / "walk.mp4"
    fps, seconds = 10.0, 120
    w = cv2.VideoWriter(str(p), cv2.VideoWriter_fourcc(*"mp4v"), fps, (160, 120))
    rng = np.random.default_rng(1)
    for i in range(int(fps * seconds)):
        t = i / fps
        if 30 <= t < 40:  # a blurry stretch: flat grey
            frame = np.full((120, 160, 3), 128, np.uint8)
        else:
            frame = rng.integers(0, 255, (120, 160, 3), dtype=np.uint8)
        w.write(frame)
    w.release()
    return p, seconds


def test_max_frames_are_spread_over_the_whole_clip(long_clip, tmp_path):
    from levanta.io.video import extract_frames

    clip, seconds = long_clip
    kept = extract_frames(clip, tmp_path / "f", fps=1.0, max_frames=12, min_sharpness=20.0)
    assert len(kept) == 12
    times = [k.time_s for k in kept]
    assert times == sorted(times)
    assert times[-1] - times[0] >= SPAN_MIN * seconds, times
    gaps = np.diff(times)
    assert gaps.max() <= GAP_RATIO_MAX * np.median(gaps), gaps
    assert not any(30 <= t < 40 for t in times), times  # the blurry stretch is skipped
    assert all(k.sharpness >= 20.0 for k in kept)
    assert all(k.path.exists() for k in kept)


def test_without_max_frames_every_sharp_window_is_kept(long_clip, tmp_path):
    from levanta.io.video import extract_frames

    clip, seconds = long_clip
    kept = extract_frames(clip, tmp_path / "f", fps=1.0, min_sharpness=20.0)
    assert seconds - 12 <= len(kept) <= seconds - 9  # 120 windows minus the 10 blurry ones
