"""The chain experiment's recomposition, checked on a network whose answer is known.

`bench/chain_policies.py` puts raw, independently solved chunks together three ways.  Before
its numbers mean anything about the real walk, it has to get the mock walk right: the mock
network returns every chunk in its own frame with its own scale (5-30 % off), so the chained
composition must recover the true cameras, keeping each chunk's own scale must not, and the
joint fit must sit between the two as its weight moves.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bench"))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # the mock network lives next door
from chain_policies import (
    HELD_OUT,
    SCENE,
    holds,
    load_chunks,
    log_scales,
    place,
    thresholds,
    winner,
)

from test_recon_chunks import MockNet, _frames, _truth


def _dumped(tmp_path, independent=True, n=30, mv=8, ov=3):
    truth = _truth(n)
    net = MockNet(truth, max_views=mv, overlap=ov, voxel=None, stride=1, chunk_dump_dir=tmp_path / "chunks", independent_chunks=independent)
    net.reconstruct(_frames(tmp_path, n))
    return truth, load_chunks(tmp_path / "chunks")


def _centre_error(truth, solved):
    got = np.array([solved[i]["T"][:3, 3] for i in range(len(truth))])
    return float(np.abs(got - np.array([T[:3, 3] for T in truth])).max())


def test_the_chain_recovers_the_true_walk_from_raw_chunks(tmp_path):
    truth, chunks = _dumped(tmp_path)
    assert len(chunks) == 6 and all(int(c["fed_poses"]) == 0 for c in chunks)
    # a millimetre over a 24 m walk: the dump keeps depth in float16 (0.1 % per pixel, as the
    # existing --keep-views dump does), three orders below the 5-10 % per link being studied;
    # measured 0.49 mm
    assert _centre_error(truth, place(chunks, log_scales(chunks, "chained"))) < 1e-3


def test_keeping_each_chunks_own_scale_does_not_on_this_network(tmp_path):
    """The mock's chunks really are 5-30 % off each other, so leaving them alone must show."""
    truth, chunks = _dumped(tmp_path)
    assert _centre_error(truth, place(chunks, log_scales(chunks, "own_scale"))) > 0.1


def test_the_joint_fit_moves_between_the_two(tmp_path):
    _, chunks = _dumped(tmp_path)
    chained = log_scales(chunks, "chained")
    loose = log_scales(chunks, "joint", lam=1e-9)
    tight = log_scales(chunks, "joint", lam=1e9)
    # no weight on the prior: the chain, up to one factor for the whole walk
    assert np.allclose(loose - loose.mean(), chained - chained.mean(), atol=1e-6)
    # all the weight on it: every chunk at the network's own scale
    assert np.allclose(tight, 0.0, atol=1e-6)


def test_without_independence_the_dump_says_poses_were_fed_in(tmp_path):
    """The experiment refuses chunks that already carry the chain; the dump has to say so."""
    _, chunks = _dumped(tmp_path, independent=False)
    assert int(chunks[0]["fed_poses"]) == 0
    assert all(int(c["fed_poses"]) == 3 for c in chunks[1:])


# today's floor IoU at every swept fps (bench/results/fps_sweep_2026-09-24.md)
TODAY_CHOSEN = {1.0: 0.6543, 2.0: 0.5506, 4.0: 0.1627, 8.0: 0.1628}
TODAY_HELD_OUT = {1.0: 0.4315, 2.0: 0.5244, 4.0: 0.6127, 8.0: 0.3202}


def _run(policy, fps, scale, iou):
    return {"policy": policy, "fps": fps, "scale_factor": scale, "floor_iou": iou}


def test_on_the_choice_scene_the_rule_is_the_one_written_first():
    """41069021: sound walk at 1 fps down to 0.60, broken chain at 4 fps to 0.50 and 1 ± 0.15."""
    th = thresholds(SCENE, TODAY_CHOSEN)
    assert th["sound"] == {1.0: pytest.approx(0.6043)}
    assert th["broken"] == (4.0, pytest.approx(0.5043))
    good = [_run("own_scale", 1.0, 1.0, 0.61), _run("own_scale", 4.0, 0.90, 0.51)]
    assert holds(good, "own_scale", SCENE, TODAY_CHOSEN)[0]
    assert not holds([good[0], _run("own_scale", 4.0, 0.84, 0.70)], "own_scale", SCENE, TODAY_CHOSEN)[0]  # 16 % off


def test_on_the_held_out_scene_a_sunk_sound_walk_fails():
    """The supervisor's case against the first version: 42897526 is best at 4 fps (0.61), and a
    policy that sinks it to 0.30 must not pass because 0.30 clears 1 fps minus 0.15."""
    th = thresholds(HELD_OUT, TODAY_HELD_OUT)
    assert th["sound"] == {1.0: pytest.approx(0.3815), 4.0: pytest.approx(0.5627)}
    assert th["broken"] == (8.0, pytest.approx(0.4627))
    sunk = [_run("joint", 1.0, 1.0, 0.45), _run("joint", 4.0, 1.0, 0.30), _run("joint", 8.0, 1.0, 0.60)]
    ok, why = holds(sunk, "joint", HELD_OUT, TODAY_HELD_OUT)
    assert not ok and any("4 fps" in w for w in why)


def test_on_the_held_out_scene_the_broken_chain_is_8_fps():
    sound = [_run("joint", 1.0, 1.0, 0.45), _run("joint", 4.0, 1.1, 0.62)]
    assert not holds(sound, "joint", HELD_OUT, TODAY_HELD_OUT)[0]  # no 8 fps run: not judged
    assert not holds([*sound, _run("joint", 8.0, 1.29, 0.62)], "joint", HELD_OUT, TODAY_HELD_OUT)[0]  # today's scale
    assert holds([*sound, _run("joint", 8.0, 1.10, 0.47)], "joint", HELD_OUT, TODAY_HELD_OUT)[0]


def test_the_winner_is_the_holder_closest_to_the_true_scale():
    rows = [_run("chained", 1.0, 1.0, 0.62), _run("chained", 4.0, 1.02, 0.60),
            _run("own_scale", 1.0, 1.0, 0.66), _run("own_scale", 4.0, 0.95, 0.70),
            _run("joint", 1.0, 1.0, 0.66), _run("joint", 4.0, 1.20, 0.70)]
    assert winner(rows, TODAY_CHOSEN) == "chained"  # joint is 20 % off and does not hold at all
    assert winner([_run("chained", 1.0, 1.0, 0.65), _run("chained", 4.0, 0.45, 0.16)], TODAY_CHOSEN) is None
