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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bench"))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # the mock network lives next door
from chain_policies import load_chunks, log_scales, place

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
