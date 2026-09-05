"""Unit tests of the building blocks."""

from __future__ import annotations

import numpy as np
import pytest

from levanta.geometry import (
    circular_mean,
    estimate_normals_pca,
    find_peaks_1d,
    quat_to_rot,
    rotation_from_a_to_b,
    voxel_downsample_indices,
)
from levanta.plan.gravity import align_to_gravity, estimate_up
from levanta.plan.occupancy import Grid, coverage_raster, free_space_raster
from levanta.plan.types import FloorPlan, Opening, Room, Wall
from levanta.plan.walls import build_wall_lines, extract_faces, manhattan_angle, merge_intervals
from levanta.recon.rgbd import backproject_frame
from levanta.scene import Camera, Frame, PointCloud


def test_quat_identity_and_rotation():
    assert np.allclose(quat_to_rot(0, 0, 0, 1), np.eye(3))
    R = quat_to_rot(0, 0, np.sin(np.pi / 4), np.cos(np.pi / 4))  # 90 deg about z
    assert np.allclose(R @ [1, 0, 0], [0, 1, 0], atol=1e-9)


def test_rotation_from_a_to_b():
    a = np.array([0.3, -0.2, 0.9])
    R = rotation_from_a_to_b(a, [0, 0, 1])
    out = R @ (a / np.linalg.norm(a))
    assert np.allclose(out, [0, 0, 1], atol=1e-9)
    assert np.allclose(R @ R.T, np.eye(3), atol=1e-9)
    R2 = rotation_from_a_to_b([0, 0, 1], [0, 0, -1])
    assert np.allclose(R2 @ [0, 0, 1], [0, 0, -1], atol=1e-9)


def test_find_peaks_and_circular_mean():
    y = np.array([0, 1, 5, 1, 0, 0, 3, 0, 0, 8, 0])
    p = find_peaks_1d(y, min_height=2, min_distance=2)
    assert list(p) == [9, 2, 6]
    ang = np.deg2rad(np.array([1, 91, 181, 271, -1, 89, 179, 269]))
    m = np.degrees(circular_mean(ang, np.pi / 2))
    assert min(abs(m), abs(m - 90)) < 1e-6


def test_voxel_downsample_keeps_one_per_voxel():
    pts = np.array([[0.001, 0, 0], [0.005, 0, 0], [0.5, 0, 0]])
    idx = voxel_downsample_indices(pts, 0.02)
    assert len(idx) == 2


def test_pca_normals_on_plane():
    rng = np.random.default_rng(0)
    pts = np.c_[rng.uniform(0, 1, (500, 2)), np.zeros(500)]
    n = estimate_normals_pca(pts, k=10)
    assert np.all(np.abs(n[:, 2]) > 0.99)


def test_gravity_alignment_recovers_tilt():
    rng = np.random.default_rng(0)
    floor = np.c_[rng.uniform(0, 4, (3000, 2)), np.zeros(3000)]
    ceil = np.c_[rng.uniform(0, 4, (2000, 2)), np.full(2000, 2.6)]
    xyz = np.r_[floor, ceil]
    nrm = np.r_[np.tile([0, 0, 1.0], (3000, 1)), np.tile([0, 0, -1.0], (2000, 1))]
    tilt = rotation_from_a_to_b([0, 0, 1], [0.2, 0.1, 0.97])
    cloud = PointCloud(xyz=xyz @ tilt.T + [1, 2, 3], normals=nrm @ tilt.T)
    up = estimate_up(cloud, hint=[0.1, 0.0, 1.0])
    assert np.dot(up, tilt @ [0, 0, 1]) > 0.9999
    aligned, g = align_to_gravity(cloud, up=up)
    assert abs(g.ceiling_height - 2.6) < 0.03
    assert np.abs(aligned.xyz[:3000, 2]).max() < 0.02


def test_coverage_and_free_space():
    grid = Grid(0.0, 0.0, 0.1, 40, 40)
    xy = np.array([[1.0, 1.0]] * 10 + [[2.0, 2.0]] * 10)
    z = np.r_[np.linspace(0.1, 2.4, 10), np.full(10, 0.5)]
    cov = coverage_raster(grid, xy, z, z_band=0.25, z_max=2.5)
    assert cov[10, 10] == 10 and cov[20, 20] == 1
    free = free_space_raster(grid, np.array([[3.0, 1.0]]), np.array([[0.5, 1.0]]))
    assert free[10, 6] and free[10, 25] and not free[10, 30]


def test_backproject_plane_and_normals():
    K = np.array([[500.0, 0, 320], [0, 500.0, 240], [0, 0, 1]])
    cam = Camera(K=K, T=np.eye(4), width=640, height=480)
    depth = np.full((480, 640), 2.0, dtype=np.float32)  # fronto-parallel wall at z = 2
    res = backproject_frame(Frame(depth=depth, camera=cam), stride=8)
    assert np.allclose(res.xyz[:, 2], 2.0)
    assert np.allclose(res.normals, [0, 0, -1.0], atol=1e-6)  # facing the camera


def test_faces_and_pairing_measure_thickness():
    rng = np.random.default_rng(0)
    n = 4000
    # face seen from the -x side at x = 1.0 (normal -x) and from the +x side at x = 1.12 (normal +x)
    y = rng.uniform(0, 3, n)
    z = rng.uniform(0.1, 2.4, n)
    xy = np.r_[np.c_[np.full(n, 1.0), y], np.c_[np.full(n, 1.12), y]] + rng.normal(0, 0.005, (2 * n, 2))
    nxy = np.r_[np.tile([-1.0, 0], (n, 1)), np.tile([1.0, 0], (n, 1))]
    faces = extract_faces(xy, nxy, np.r_[z, z], 0.0, min_bands=3)
    assert len(faces) == 2
    lines = build_wall_lines(faces, 0.0)
    assert len(lines) == 1 and lines[0].sides_seen == 2
    assert abs(lines[0].thickness - 0.12) < 0.01
    assert abs(lines[0].s - 1.06) < 0.01


def test_manhattan_angle():
    ang = np.deg2rad(np.r_[np.full(100, 17.0), np.full(100, 107.0), np.full(50, 197.0)])
    nxy = np.c_[np.cos(ang), np.sin(ang)]
    assert abs(np.degrees(manhattan_angle(nxy)) - 17.0) < 1e-6


def test_merge_intervals():
    assert merge_intervals([(0, 1), (1.05, 2), (3, 4)], gap=0.1) == [(0.0, 2.0), (3.0, 4.0)]


def test_floorplan_roundtrip(tmp_path):
    plan = FloorPlan(
        walls=[Wall(0, (0, 0), (4, 0), 0.2, 2.5, 1), Wall(1, (4, 0), (4, 3), 0.2, 2.5, 2)],
        rooms=[Room(0, "Room 1", [(0, 0), (4, 0), (4, 3), (0, 3)])],
        openings=[Opening(0, 0, "door", 1.0, 1.9, 0.0, 2.05, rooms=(0,))],
        ceiling_height=2.5,
    )
    p = tmp_path / "plan.json"
    plan.to_json(p)
    back = FloorPlan.from_json(p)
    assert back.walls[1].b == (4, 3) and back.openings[0].rooms == (0,)
    assert abs(back.rooms[0].area - 12.0) < 1e-9
    assert plan.total_area == pytest.approx(12.0)


def test_pointcloud_ply_roundtrip(tmp_path):
    rng = np.random.default_rng(0)
    c = PointCloud(
        xyz=rng.uniform(0, 1, (50, 3)),
        normals=np.tile([0, 0, 1.0], (50, 1)),
        colors=rng.integers(0, 255, (50, 3)).astype(np.uint8),
        view=np.zeros(50, dtype=np.int32),
        cameras=np.eye(4)[None],
    )
    p = tmp_path / "c.ply"
    c.save_ply(p)
    d = PointCloud.load_ply(p)
    assert np.allclose(c.xyz, d.xyz, atol=1e-6) and d.cameras.shape == (1, 4, 4) and d.colors.shape == (50, 3)
