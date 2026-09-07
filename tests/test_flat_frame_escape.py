"""A plain wall filling the frame scores like a title card, and a plain wall is the house.

The filter exists because a produced tour opens with text on black, which is both flat and
the sharpest thing in the clip by variance of the Laplacian.  Its own docstring already said
a plain wall would trip it, and it shipped anyway.  Measured on a rendered walk with no title
cards in it at all, `levanta check` reported "30 s of title cards or blank frames: skipped
(they are not the house)" and a third of the footage was dropped.

`--keep-flat` (and `extract_frames(flat_max=...)`) is the escape hatch that made the cost
measurable: on that walk it recovers 16 of the 80 frames and takes the plan from 10.27 m² to
13.31 m² against a truth of 56.8.  So the filter costs about 3 m², which is real and is not
the reason the plan is a fifth of the flat.
"""

from __future__ import annotations

import numpy as np

from levanta.io.video import FLAT_MAX, _flatness, _usable


def _plain_wall(shade: int = 150) -> np.ndarray:
    rng = np.random.default_rng(4)
    return np.clip(shade + rng.normal(0, 2.0, (360, 640)), 0, 255).astype(np.uint8)


def _textured_room() -> np.ndarray:
    rng = np.random.default_rng(4)
    return rng.integers(0, 255, (360, 640), dtype=np.uint8)


def test_a_plain_wall_looks_flat_like_a_title_card():
    assert _flatness(_plain_wall()) > FLAT_MAX
    assert _flatness(_textured_room()) <= FLAT_MAX


def test_the_filter_throws_the_wall_away_by_default():
    assert _usable(_plain_wall()) == 0.0


def test_raising_the_bar_keeps_it():
    assert _usable(_plain_wall(), flat_max=1.01) > 0.0


def test_a_textured_frame_is_kept_either_way():
    assert _usable(_textured_room()) > 0.0
    assert _usable(_textured_room(), flat_max=1.01) > 0.0
