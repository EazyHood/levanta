"""Title cards and blank frames never reach the network.

The first real walkthrough (a real-estate tour, CC BY) opens and closes with white text on
black.  Text on black is the *sharpest* thing in the clip by variance of the Laplacian
(2 000-5 700 against 60-900 for the rooms), so the sharpness pick chose six title cards
out of 24 frames and MapAnything built its scene around them.

Measured on those 24 frames before the fix: the fraction of pixels inside the dominant
band of 9 grey levels is 0.87-0.98 for the cards and 0.07-0.31 for the rooms.
Threshold written before the fix ran: FLAT_MAX = 0.6.
"""

from __future__ import annotations

import numpy as np
import pytest

FLAT_MAX = 0.6


def _title_card(w=320, h=180):
    cv2 = pytest.importorskip("cv2")
    img = np.zeros((h, w, 3), np.uint8)
    cv2.putText(img, "one bedroom tour", (10, 90), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
    cv2.putText(img, "call the office", (10, 140), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
    return img


def test_flatness_separates_cards_from_rooms():
    from levanta.io.video import _flatness, _sharpness

    cv2 = pytest.importorskip("cv2")
    card = cv2.cvtColor(_title_card(), cv2.COLOR_BGR2GRAY)
    room = np.random.default_rng(3).integers(0, 255, (180, 320), dtype=np.uint8)
    wall = (np.linspace(120, 180, 320, dtype=np.uint8)[None, :] + np.zeros((180, 1), np.uint8))  # a plain wall in raking light
    assert _flatness(card) > FLAT_MAX and _sharpness(card) > 20  # sharp, yet a card
    assert _flatness(room) < FLAT_MAX
    assert _flatness(wall) < FLAT_MAX  # a gradient is not a card


@pytest.fixture
def clip_with_cards(tmp_path):
    cv2 = pytest.importorskip("cv2")
    p = tmp_path / "tour.mp4"
    fps, seconds = 10.0, 30
    w = cv2.VideoWriter(str(p), cv2.VideoWriter_fourcc(*"mp4v"), fps, (320, 180))
    rng = np.random.default_rng(5)
    for i in range(int(fps * seconds)):
        t = i / fps
        if t < 4 or t >= 26:  # opening and closing cards
            frame = _title_card()
        else:
            frame = rng.integers(0, 255, (180, 320, 3), dtype=np.uint8)
        w.write(frame)
    w.release()
    return p


def test_cards_are_skipped_and_reported(clip_with_cards, tmp_path):
    from levanta.io.video import extract_frames, inspect_video

    kept = extract_frames(clip_with_cards, tmp_path / "f", fps=1.0, max_frames=10)
    assert kept and all(4 <= k.time_s < 26 for k in kept), [k.time_s for k in kept]
    rep = inspect_video(clip_with_cards, fps=1.0)
    assert rep["flat_windows"] >= 6  # 4 s opening + 4 s closing at 1 fps
    assert any("title" in w or "blank" in w for w in rep["warnings"])
