"""A long walk is reconstructed in overlapping chunks that land in one world frame.

MapAnything takes ``max_views`` images at a time (VRAM).  The first real walkthrough (220 s)
spread 24 frames over the whole clip: consecutive views were 1-5 m apart, the network
could not register them and masked the rooms out (1-21 points per view).  Now consecutive
frames go in chunks of ``max_views``; every chunk after the first starts with ``overlap``
views of the previous one, passed to the network with their known poses and intrinsics,
and the chunk's output is aligned onto those views (similarity: scale, rotation,
translation) before fusing.

Thresholds written before the fix ran, on a mock network that returns each chunk in its
own frame with its own scale:
- every frame is fused exactly once;
- the recovered camera centres match the truth within 1e-6 m and the fused points sit
  at the world's scale in front of every camera (a chunk left at its own scale is 10-30 % off);
- the number of network calls is ceil((n - max_views) / (max_views - overlap)) + 1.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from levanta.recon.mapanything import MapAnythingBackend, align_similarity
from levanta.scene import Frame

TOL = 1e-6
H, W = 16, 20  # the mock network's picture size
K_MOCK = np.array([[16.0, 0, (W - 1) / 2], [0, 16.0, (H - 1) / 2], [0, 0, 1]])


def _rot(axis, deg):
    axis = np.asarray(axis, float) / np.linalg.norm(axis)
    a = math.radians(deg)
    K = np.array([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]])
    return np.eye(3) + math.sin(a) * K + (1 - math.cos(a)) * K @ K


def _truth(n):
    """Cameras walking along a bent path, looking down a little."""
    poses = []
    for i in range(n):
        R = _rot([0, 0, 1], 15 * i) @ _rot([1, 0, 0], -10)
        c = np.array([0.8 * i, 0.3 * math.sin(i / 2), 1.4])
        T = np.eye(4)
        T[:3, :3] = R
        T[:3, 3] = c
        poses.append(T)
    return poses


class MockNet(MapAnythingBackend):
    """Returns every chunk in the frame of its first view, scaled by a chunk-specific factor."""

    def __init__(self, truth, **kw):
        super().__init__(**kw)
        self.truth = truth
        self.calls = 0

    def predict_views(self, image_paths, intrinsics=None, poses=None):
        self.calls += 1
        idx = [int(Path(p).stem.split("_")[1]) for p in image_paths]
        # the first chunk defines the world (there is nothing to align it to); every later
        # chunk comes back in the frame of its own first view, with its own metric scale
        s = 1.0 if self.calls == 1 else 1.0 + 0.05 * self.calls
        T0 = np.eye(4) if self.calls == 1 else self.truth[idx[0]]
        out = []
        for i in idx:
            T = np.linalg.inv(T0) @ self.truth[i]
            T = T.copy()
            T[:3, 3] *= s
            # a shallow pyramid 2.0-2.3 m away (a room corner, not a picture; no depth edges)
            yy, xx = np.mgrid[0:H, 0:W]
            depth = (s * (2.0 + 0.15 * (np.abs(xx - (W - 1) / 2) / ((W - 1) / 2) + np.abs(yy - (H - 1) / 2) / ((H - 1) / 2)))).astype(np.float32)
            out.append({"depth": depth, "mask": np.ones((H, W), bool), "K": K_MOCK.copy(), "T": T, "image": np.zeros((H, W, 3), np.uint8), "conf": None})
        return out


def _frames(tmp_path, n):
    cv2 = pytest.importorskip("cv2")
    out = []
    for i in range(n):
        p = tmp_path / f"frame_{i:05d}.jpg"
        cv2.imwrite(str(p), np.full((H, W, 3), 127, np.uint8))  # the mock's K is for these pixels
        out.append(Frame(path=p))
    return out


def test_a_view_that_is_one_flat_picture_is_dropped(tmp_path):
    """The intro graphic of the first real walkthrough came back as a plane 0.6 m in front
    of the camera covering 90 % of the frame; the rooms behind it were masked out."""

    class Picture(MockNet):
        def predict_views(self, image_paths, intrinsics=None, poses=None):
            out = super().predict_views(image_paths, intrinsics, poses)
            if self.calls == 1:
                out[1]["depth"] = np.full((H, W), 0.6, np.float32)  # a picture, not a room
            return out

    truth = _truth(5)
    net = Picture(truth, max_views=8, overlap=3, voxel=None, stride=1)
    cloud = net.reconstruct(_frames(tmp_path, 5))
    assert cloud.meta["views_dropped_flat"] == 1 and cloud.meta["views"] == 5
    assert not (cloud.view == 1).any() and (cloud.view == 0).any()


def test_chunks_land_in_one_world_frame(tmp_path):
    n, max_views, overlap = 30, 8, 3
    truth = _truth(n)
    net = MockNet(truth, max_views=max_views, overlap=overlap, voxel=None, stride=1)
    cloud = net.reconstruct(_frames(tmp_path, n))
    assert net.calls == math.ceil((n - max_views) / (max_views - overlap)) + 1
    assert cloud.meta["views"] == n and len(cloud.cameras) == n
    centres = cloud.cameras[:, :3, 3]
    err = np.linalg.norm(centres - np.array([T[:3, 3] for T in truth]), axis=1)
    assert err.max() < TOL, err.max()
    # depths were brought back to the world's scale: the pyramid sits 2.0-2.3 m in front of
    # every camera (the border pixels go with the normals; what survives averages ~2.10);
    # a chunk left at its own scale would be 10-30 % off
    for v in range(n):
        pts = cloud.xyz[cloud.view == v]
        assert len(pts) > 0
        local = (np.linalg.inv(truth[v]) @ np.c_[pts, np.ones(len(pts))].T).T[:, :3]
        z = local[:, 2]
        assert 1.95 < z.min() and z.max() < 2.35 and abs(z.mean() - 2.10) < 0.05, (v, z.min(), z.max(), z.mean())


def test_short_walk_is_one_call(tmp_path):
    truth = _truth(5)
    net = MockNet(truth, max_views=8, overlap=3, voxel=None, stride=1)
    net.reconstruct(_frames(tmp_path, 5))
    assert net.calls == 1


def test_align_similarity_recovers_scale_rotation_translation():
    truth = _truth(4)
    s, R, t = 1.07, _rot([0, 1, 0], 33), np.array([1.0, -2.0, 0.5])
    moved = []
    for T in truth:
        M = T.copy()
        M[:3, :3] = R.T @ T[:3, :3]
        M[:3, 3] = (R.T @ (T[:3, 3] - t)) / s  # the chunk's own frame and scale
        moved.append(M)
    S = align_similarity(moved, truth)  # maps chunk -> world
    for M, T in zip(moved, truth, strict=True):
        W = S.apply(M)
        assert np.abs(W - T).max() < TOL
    assert abs(S.scale - s) < TOL


def test_align_similarity_needs_two_views():
    with pytest.raises(ValueError):
        align_similarity([np.eye(4)], [np.eye(4)])
