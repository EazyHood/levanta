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
