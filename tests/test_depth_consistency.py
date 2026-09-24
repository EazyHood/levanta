"""The depth-scale estimator on a room whose answer is known.

A box room, cameras walking inside it, depth computed exactly by ray casting.  Scaling the
depths and leaving the poses alone reproduces what the network does on the rendered flat
(depth at 0.55, cameras right); the estimator has to find the inverse from the poses and the
depths alone, with nothing told.  Thresholds written before it ran: true depths give scales
within 2 % of 1, a uniform 0.55 gives 1/0.55 within 3 %, per-view factors from 0.4 to 0.7 are
each recovered within 5 %, and cameras that only turn in place are reported as not estimable.
"""

from __future__ import annotations

import math

import numpy as np

from levanta.recon.depth_consistency import consistent_depth_scales

H, W = 48, 64
K = np.array([[50.0, 0, W / 2], [0, 50.0, H / 2], [0, 0, 1]])
LO, HI = np.array([0.0, 0.0, 0.0]), np.array([4.0, 3.0, 2.5])  # z up


def _pose(centre, yaw_deg, tilt=-0.15):
    f = np.array([math.cos(math.radians(yaw_deg)), math.sin(math.radians(yaw_deg)), tilt])
    f /= np.linalg.norm(f)
    x = np.cross(f, [0, 0, 1.0])
    x /= np.linalg.norm(x)
    y = np.cross(f, x)
    T = np.eye(4)
    T[:3, 0], T[:3, 1], T[:3, 2], T[:3, 3] = x, y, f, centre
    return T


def _depth(T):
    ys, xs = np.mgrid[0:H, 0:W]
    rays = np.linalg.inv(K) @ np.vstack([xs.ravel() + 0.5, ys.ravel() + 0.5, np.ones(H * W)])
    d = T[:3, :3] @ rays
    c = T[:3, 3][:, None]
    with np.errstate(divide="ignore", invalid="ignore"):
        t_hi = np.where(d > 0, (HI[:, None] - c) / d, np.inf)
        t_lo = np.where(d < 0, (LO[:, None] - c) / d, np.inf)
    t = np.minimum(t_hi, t_lo).min(axis=0)  # the first wall, floor or ceiling hit
    return t.reshape(H, W)  # rays have z = 1 in the camera, so t is the z-depth


def _walk(factors=None):
    centres = [(0.8 + 0.25 * k, 0.9 + 0.12 * k, 1.4) for k in range(8)]
    yaws = [20 * k for k in range(8)]
    views = []
    for k, (c, yaw) in enumerate(zip(centres, yaws, strict=True)):
        T = _pose(np.array(c), yaw)
        f = 1.0 if factors is None else factors[k]
        views.append({"depth": _depth(T) * f, "mask": np.ones((H, W), bool), "K": K, "T": T})
    return views


def test_true_depths_come_back_at_one():
    s, rep = consistent_depth_scales(_walk())
    assert rep["estimable"]
    assert np.allclose(s, 1.0, atol=0.02), s


def test_a_uniform_bias_is_undone_from_the_poses_alone():
    s, _ = consistent_depth_scales(_walk([0.55] * 8))
    assert np.allclose(s, 1 / 0.55, rtol=0.03), s


def test_each_view_gets_its_own_scale_back():
    factors = [0.4, 0.7, 0.55, 0.62, 0.45, 0.68, 0.5, 0.6]
    s, _ = consistent_depth_scales(_walk(factors))
    assert np.allclose(s * np.array(factors), 1.0, rtol=0.05), s * np.array(factors)


def test_turning_in_place_carries_no_scale():
    views = []
    for yaw in range(0, 160, 20):
        T = _pose(np.array([2.0, 1.5, 1.4]), yaw)
        views.append({"depth": _depth(T) * 0.55, "mask": np.ones((H, W), bool), "K": K, "T": T})
    s, rep = consistent_depth_scales(views)
    assert not rep["estimable"] and np.allclose(s, 1.0)


# Option C's wall direction, on the same box room: a reconstruction turned by some angle about
# the vertical must read as turned by that angle, modulo 90 degrees, and C must turn it back.
def _rz(deg):
    a = math.radians(deg)
    R = np.eye(4)
    R[:2, :2] = [[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]]
    return R


def _chunk(poses, reported):
    return [{"depth": _depth(T), "mask": np.ones((H, W), bool), "K": K, "T": Tr} for T, Tr in zip(poses, reported, strict=True)]


def test_the_wall_direction_turns_with_the_reconstruction():
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bench"))
    from chain_policies import wall_yaw

    poses = [_pose(np.array([0.8 + 0.3 * k, 0.9 + 0.15 * k, 1.4]), 25 * k) for k in range(6)]
    up = np.array([0.0, 0.0, 1.0])
    base, clarity = wall_yaw(_chunk(poses, poses), up)
    turned, _ = wall_yaw(_chunk(poses, [_rz(10) @ T for T in poses]), up)
    assert clarity > 0.5
    assert abs(math.degrees(turned - base) - 10) < 1.0


def test_option_c_turns_a_chunk_back_onto_the_walk():
    """Chunk 1 comes back from the network turned 12 degrees inside itself, all but the two frames
    it shares; the chain alone leaves it turned, C brings it back at least halfway."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bench"))
    from chain_policies import place, place_yaw_from_walls, wall_yaw

    first = [_pose(np.array([0.8 + 0.2 * k, 0.9 + 0.1 * k, 1.4]), 30 * k) for k in range(6)]
    second = first[-2:] + [_pose(np.array([1.9 + 0.2 * k, 1.5 - 0.1 * k, 1.4]), 150 + 30 * k) for k in range(6)]
    pivot = first[-1][:3, 3]
    turn = np.eye(4)
    turn[:3, :3] = _rz(12)[:3, :3]
    turn[:3, 3] = pivot - turn[:3, :3] @ pivot
    raw_second = second[:2] + [turn @ T for T in second[2:]]

    def pack(true_poses, reported, idx, shared):
        return {"idx": np.array(idx), "shared": np.int32(shared), "depth": np.stack([_depth(T) for T in true_poses]),
                "mask": np.ones((len(idx), H, W), bool), "K": np.stack([K] * len(idx)), "T": np.stack(reported)}

    chunks = [pack(first, first, list(range(6)), 0), pack(second, raw_second, list(range(4, 12)), 2)]
    up = np.array([0.0, 0.0, 1.0])

    def error(solved):
        got, _ = wall_yaw([solved[i] for i in range(6, 12)], up)
        ref, _ = wall_yaw([solved[i] for i in range(6)], up)
        return abs(math.degrees((got - ref + math.pi / 4) % (math.pi / 2) - math.pi / 4))

    x = np.zeros(2)
    chain_err = error(place(chunks, x))
    c_err = error(place_yaw_from_walls(chunks, x))
    assert chain_err > 8
    assert c_err < chain_err / 2
