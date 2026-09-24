"""The laps experiment's two pieces that decide it, checked before it runs.

The walk has to change only in length: three laps are the same frames there, back and there
again, with no jump and no frame shown twice in a row.  And the verdict is the rule written in
`bench/replica_laps.py` before any run: at three laps, scale within 15 % and floor IoU no more
than 0.05 below one lap's.
"""

from __future__ import annotations

import sys
from itertools import pairwise
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bench"))
from replica_laps import holds, lap_sequence

from levanta.plan.types import chunk_count


def test_three_laps_are_the_same_frames_there_back_and_there():
    seq = lap_sequence(116, 3)
    assert len(seq) == 346 and seq[:116] == list(range(116))
    assert seq[116] == 114 and seq[230] == 0 and seq[231] == 1 and seq[-1] == 115
    # no jump: every step moves to a neighbouring frame of the rendered walk
    assert all(abs(a - b) == 1 for a, b in pairwise(seq))
    assert lap_sequence(116, 1) == list(range(116))


def test_only_the_chain_length_changes():
    assert chunk_count(len(lap_sequence(116, 1))) == 6
    assert chunk_count(len(lap_sequence(116, 3))) == 18


def test_the_rule_as_written():
    one = {"scale_factor": 1.03, "floor_iou": 0.60}
    assert holds(one, {"scale_factor": 0.86, "floor_iou": 0.55})[0]
    assert not holds(one, {"scale_factor": 0.84, "floor_iou": 0.60})[0]
    assert not holds(one, {"scale_factor": 1.00, "floor_iou": 0.54})[0]
